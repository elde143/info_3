import os
import sys
import time
import json
import shutil
import atexit
import subprocess
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ════════════════════════════════════════
#  폴더 및 파일 설정
# ════════════════════════════════════════
SANDBOX_DIR        = 'sandbox'
SUBMISSIONS_DIR    = 'submissions'
SHARED_DIR         = 'shared_files'
PROBLEMS_FILE      = 'problems.json'
EXAM_PROBLEMS_FILE = 'exam_problems.json'
CONFIG_FILE        = 'config.json'

for d in [SANDBOX_DIR, SUBMISSIONS_DIR, SHARED_DIR]:
    os.makedirs(d, exist_ok=True)

# 서버 시작 및 종료 시 샌드박스 정리
if os.path.exists(SANDBOX_DIR):
    shutil.rmtree(SANDBOX_DIR, ignore_errors=True)
os.makedirs(SANDBOX_DIR, exist_ok=True)

def cleanup_sandbox():
    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR, ignore_errors=True)
atexit.register(cleanup_sandbox)

# ════════════════════════════════════════
#  데이터 파일 로드/저장 함수들
# ════════════════════════════════════════
DEFAULT_CONFIG = {
    'exam_title': '설정된 수행평가가 없습니다.',
    'exam_desc' : '',
    'exam_initial_code' : '',
    'exam_test_cases': [],
    'exam_active': False,
    'exam_submitted_ips': [],
    'practice_categories': ['일반']
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_problems(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_problems(filepath, problems):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(problems, f, ensure_ascii=False, indent=2)

# ════════════════════════════════════════
#  보안 (금지어 설정)
# ════════════════════════════════════════
BLOCKED = [
    'import os', 'import sys', 'import subprocess', 'import shutil', 
    'import socket', 'import requests', '__import__', 'eval(', 'exec(', 
    'open(\'/', 'open(\"/', 'rmdir', 'remove', 'unlink', 'system(', 'popen('
]

def is_safe_code(code):
    for kw in BLOCKED:
        if kw in code:
            return False, f'⛔ 보안상 사용할 수 없는 코드입니다: {kw}'
    return True, ''

# ════════════════════════════════════════
#  학생: 페이지 렌더링 및 코드 실행
# ════════════════════════════════════════
@app.route('/')
def index():
    cfg = load_config()
    already_submitted = False
    if cfg.get('exam_active', False) and request.remote_addr in cfg.get('exam_submitted_ips', []):
        already_submitted = True
    return render_template('index.html', config=cfg, already_submitted=already_submitted)

@app.route('/run', methods=['POST'])
def run_code():
    data = request.json
    code = data.get('code', '')
    inputs = data.get('inputs', [])
    sid = data.get('student_id', '').strip() or data.get('session_id', 'anonymous')
    
    folder_name = re.sub(r'[^a-zA-Z0-9_-]', '', sid)
    tmp_dir = os.path.abspath(os.path.join(SANDBOX_DIR, folder_name))
    os.makedirs(tmp_dir, exist_ok=True)

    safe, msg = is_safe_code(code)
    if not safe:
        return jsonify({'output': '', 'error': msg})

    try:
        # 공유 파일 복사
        if os.path.exists(SHARED_DIR):
            for sf in os.listdir(SHARED_DIR):
                src = os.path.join(SHARED_DIR, sf)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(tmp_dir, sf))

        # 학생 코드 저장 (UTF-8 패치 포함)
        code_path = os.path.join(tmp_dir, 'student_code.py')
        patch = """import builtins\n_o = builtins.open\ndef _u(*a, **k):\n    if 'encoding' not in k: k['encoding']='utf-8'\n    return _o(*a, **k)\nbuiltins.open = _u\n"""
        with open(code_path, 'w', encoding='utf-8') as f:
            f.write(patch + code)

        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        stdin_data = '\n'.join(inputs) + '\n' if inputs else ''
        
        proc = subprocess.Popen(
            [sys.executable, '-X', 'utf8', 'student_code.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=env, cwd=tmp_dir
        )
        
        status = 'finished'
        try:
            out, err = proc.communicate(input=stdin_data, timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            status = 'waiting'
            if not err: err = ''
            
        if err and 'EOFError' in err:
            status = 'waiting'
            err = ''
            
    except Exception as e:
        out = ''
        err = str(e)
        status = 'error'
        
    return jsonify({'output': out, 'error': err, 'status': status})

@app.route('/api/sandbox_files', methods=['POST'])
def get_sandbox_files():
    data = request.json
    sid = data.get('student_id', '').strip() or data.get('session_id', 'anonymous')
    folder_name = re.sub(r'[^a-zA-Z0-9_-]', '', sid)
    tmp_dir = os.path.abspath(os.path.join(SANDBOX_DIR, folder_name))
    
    os.makedirs(tmp_dir, exist_ok=True)
    if os.path.exists(SHARED_DIR):
        for sf in os.listdir(SHARED_DIR):
            src = os.path.join(SHARED_DIR, sf)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(tmp_dir, sf))
    
    files = []
    if os.path.exists(tmp_dir):
        for fname in sorted(os.listdir(tmp_dir)):
            if fname not in ['student_code.py', 'wrapper.py', '_meta.json', '__pycache__']:
                filepath = os.path.join(tmp_dir, fname)
                if os.path.isfile(filepath):
                    files.append({'name': fname, 'size': os.path.getsize(filepath)})
    return jsonify(files)

# ════════════════════════════════════════
#  자동 채점 API
# ════════════════════════════════════════
@app.route('/judge', methods=['POST'])
def judge_code():
    data = request.json
    code = data.get('code', '')
    pid = str(data.get('problem_id', '0'))
    sid = data.get('student_id', 'anon').strip()
    
    tc = []
    if pid == 'exam':
        tc = load_config().get('exam_test_cases', [])
        if not tc: return jsonify({'status': 'error', 'message': '수행평가에 등록된 테스트 케이스가 없습니다.'})
    else:
        probs = load_problems(PROBLEMS_FILE)
        prob = next((p for p in probs if str(p['id']) == pid), None)
        if not prob: return jsonify({'status': 'error', 'message': '문제를 찾을 수 없습니다.'})
        tc = prob.get('test_cases', [])
        if not tc: return jsonify({'status': 'error', 'message': '이 문제에는 등록된 테스트 케이스가 없습니다.'})

    safe, msg = is_safe_code(code)
    if not safe: return jsonify({'status': 'error', 'message': msg})
    
    folder_name = re.sub(r'[^a-zA-Z0-9_-]', '', sid) + f"_judge_{int(time.time()*100)}"
    tmp_dir = os.path.abspath(os.path.join(SANDBOX_DIR, folder_name))
    os.makedirs(tmp_dir, exist_ok=True)
    
    if os.path.exists(SHARED_DIR):
        for sf in os.listdir(SHARED_DIR):
            if os.path.isfile(os.path.join(SHARED_DIR, sf)):
                shutil.copy2(os.path.join(SHARED_DIR, sf), os.path.join(tmp_dir, sf))

    with open(os.path.join(tmp_dir, 'student_code.py'), 'w', encoding='utf-8') as f:
        f.write(code)
        
    wrapper = """import sys, time, tracemalloc, json, builtins
_o = builtins.open
def _u(*a,**k):
    if 'encoding' not in k: k['encoding']='utf-8'
    return _o(*a,**k)
builtins.open = _u
tracemalloc.start()
st = time.perf_counter()
try:
    with open('student_code.py','r',encoding='utf-8') as f:
        exec(f.read(), {'__name__': '__main__'})
except SystemExit:
    pass
except Exception as e:
    print(e, file=sys.stderr)
et = time.perf_counter()
cm, pm = tracemalloc.get_traced_memory()
tracemalloc.stop()
with open('_meta.json','w',encoding='utf-8') as f:
    json.dump({'t': et-st, 'm': pm}, f)
"""
    with open(os.path.join(tmp_dir, 'wrapper.py'), 'w', encoding='utf-8') as f:
        f.write(wrapper)

    env = os.environ.copy()
    env['PYTHONUTF8'], env['PYTHONIOENCODING'] = '1', 'utf-8'
    mt, mm = 0.0, 0

    for i, t in enumerate(tc):
        inp = t.get('input', '')
        exp = t.get('output', '').strip()
        inp = inp + '\n' if inp and not inp.endswith('\n') else inp
        
        proc = subprocess.Popen(
            [sys.executable, '-X', 'utf8', 'wrapper.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=env, cwd=tmp_dir
        )
        try:
            out, err = proc.communicate(input=inp, timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            return jsonify({'status': 'fail', 'message': f'시간 초과 (Test Case {i+1})'})
        
        if err:
            return jsonify({'status': 'error', 'message': f'런타임 에러 (Test Case {i+1})', 'error': err})

        meta_p = os.path.join(tmp_dir, '_meta.json')
        if os.path.exists(meta_p):
            with open(meta_p, 'r') as mf:
                m = json.load(mf)
                mt = max(mt, m.get('t', 0.0))
                mm = max(mm, m.get('m', 0))

        if out.strip() != exp:
            return jsonify({'status': 'fail', 'message': f'오답 (Test Case {i+1} 실패)', 'expected': exp, 'actual': out.strip()})

    return jsonify({
        'status': 'success', 'message': '정답입니다!', 
        'time_sec': round(mt, 4), 'memory_kb': round(mm/1024, 2)
    })

# ════════════════════════════════════════
#  학생 제출 API
# ════════════════════════════════════════
@app.route('/submit', methods=['POST'])
def submit():
    data = request.json
    student_id = data.get('student_id')
    name = data.get('name')
    code = data.get('code')
    problem_id = data.get('problem_id')
    
    # 1. 학생이 보낸 'is_final' 신호를 여기서 읽어야 합니다! (이 줄이 핵심)
    is_final = data.get('is_final', False)

    if not all([student_id, name, code, problem_id]):
        return jsonify({'success': False, 'message': '데이터가 누락되었습니다.'})

    # 2. 신호가 왔을 때만 [최종]을 붙이도록 로직을 바꿉니다.
    if is_final:
        prefix = "[최종]"
    else:
        config = load_config()
        prefix = "[시험]" if config.get('exam_active') else "[연습]"
        
    filename = f"{prefix}_{student_id}_{name}_{problem_id}.py"
    filepath = os.path.join(SUBMISSIONS_DIR, filename)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(code)
        # 성공 메시지에 [최종]이 뜨는지 확인할 수 있게 리턴합니다.
        return jsonify({'success': True, 'message': f'제출 완료! ({prefix})'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
# ════════════════════════════════════════
#  교사: 페이지 렌더링 API
# ════════════════════════════════════════
@app.route('/teacher/')
def teacher():
    return render_template('teacher.html', config=load_config())

@app.route('/api/submissions')
def get_submissions():
    subs = []
    if not os.path.exists(SUBMISSIONS_DIR): return subs
    for fn in os.listdir(SUBMISSIONS_DIR):
        # [수정] .py 확장자 체크를 하지 않거나, 더 유연하게 바꿉니다.
        # if not fn.endswith('.py'): continue  <-- 이 줄을 삭제하거나 아래처럼 처리

        # 파일명에서 .py가 있으면 떼고, 없으면 그대로 둡니다.
        name_only = fn[:-3] if fn.endswith('.py') else fn
        parts = name_only.split('_')
        
        sid, nm, pid = "알수없음", "알수없음", "0"
        
        # 1. [최종]_학번_이름_문제 형식 (덩어리 4개)
        if fn.startswith('[최종]') and len(parts) >= 4:
            sid = parts[1]
            nm  = parts[2]
            pid = parts[3]
        # 2. 일반 학번_이름_문제 형식 (덩어리 3개)
        elif len(parts) >= 3:
            sid = parts[0]
            nm  = parts[1]
            pid = parts[2]
        else:
            # 형식이 조금 달라도 일단 목록엔 띄웁니다.
            sid = parts[0] if len(parts) > 0 else "형식오류"

        subs.append({
            'filename': fn,
            'student_id': sid,
            'name': nm,
            'problem_id': pid,
            'time': datetime.fromtimestamp(os.path.getmtime(os.path.join(SUBMISSIONS_DIR, fn))).strftime('%Y-%m-%d %H:%M:%S')
        })
    return subs
@app.route('/teacher/set_exam', methods=['POST'])
def set_exam():
    cfg = load_config()
    cfg.update({
        'exam_title': request.json.get('exam_title', ''),
        'exam_desc': request.json.get('exam_desc', ''),
        'exam_initial_code': request.json.get('exam_initial_code', ''),
        'exam_test_cases': request.json.get('exam_test_cases', [])
    })
    save_config(cfg)
    return jsonify({'success': True, 'message': '✅ 수행평가가 셋팅되었습니다!'})

@app.route('/teacher/toggle_exam', methods=['POST'])
def toggle_exam():
    cfg = load_config()
    active = request.json.get('active', False)
    if active and not cfg.get('exam_active'):
        cfg['exam_submitted_ips'] = []
    cfg['exam_active'] = active
    save_config(cfg)
    return jsonify({'success': True, 'message': f'✅ 시험이 {"공개" if active else "비공개"}로 전환되었습니다.'})

@app.route('/teacher/view/<filename>')
def view_sub(filename):
    p = os.path.join(SUBMISSIONS_DIR, os.path.basename(filename))
    if not os.path.exists(p): return '파일을 찾을 수 없습니다.', 404
    with open(p, 'r', encoding='utf-8') as f:
        return f'<pre style="font-family:monospace; padding:20px;">{f.read()}</pre>'

# ════════════════════════════════════════
#  교사: 항목(카테고리) 관리 API
# ════════════════════════════════════════
@app.route('/api/categories/add', methods=['POST'])
def add_category():
    cfg = load_config()
    new_cat = request.json.get('category', '').strip()
    cats = cfg.get('practice_categories', ['일반'])
    if new_cat and new_cat not in cats:
        cats.append(new_cat)
        cfg['practice_categories'] = cats
        save_config(cfg)
    return jsonify({'success': True})

@app.route('/api/categories/update', methods=['POST'])
def update_category():
    cfg = load_config()
    old_cat = request.json.get('old_cat', '').strip()
    new_cat = request.json.get('new_cat', '').strip()
    cats = cfg.get('practice_categories', ['일반'])
    if old_cat in cats and new_cat and new_cat not in cats:
        cats[cats.index(old_cat)] = new_cat
        cfg['practice_categories'] = cats
        save_config(cfg)
        
        probs = load_problems(PROBLEMS_FILE)
        changed = False
        for p in probs:
            if p.get('category') == old_cat:
                p['category'] = new_cat
                changed = True
        if changed: save_problems(PROBLEMS_FILE, probs)
    return jsonify({'success': True})

@app.route('/api/categories/delete', methods=['POST'])
def delete_category():
    cfg = load_config()
    cat = request.json.get('category', '').strip()
    cats = cfg.get('practice_categories', ['일반'])
    if cat in cats and cat != '일반':
        cats.remove(cat)
        cfg['practice_categories'] = cats
        save_config(cfg)
        
        probs = load_problems(PROBLEMS_FILE)
        changed = False
        for p in probs:
            if p.get('category') == cat:
                p['category'] = '일반'
                changed = True
        if changed: save_problems(PROBLEMS_FILE, probs)
    return jsonify({'success': True})

@app.route('/api/categories/reorder', methods=['POST'])
def reorder_categories():
    cfg = load_config()
    cfg['practice_categories'] = request.json.get('categories', ['일반'])
    save_config(cfg)
    return jsonify({'success': True})

# ════════════════════════════════════════
#  교사: 파일 관리 API
# ════════════════════════════════════════
@app.route('/teacher/shared_files')
def shared_files_list():
    lst = []
    for f in sorted(os.listdir(SHARED_DIR)):
        p = os.path.join(SHARED_DIR, f)
        if os.path.isfile(p):
            lst.append({
                'name': f, 
                'size': os.path.getsize(p), 
                'modified': datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M:%S')
            })
    return jsonify(lst)

@app.route('/teacher/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'success': False, 'message': '파일이 없습니다.'})
    f = request.files['file']
    f.save(os.path.join(SHARED_DIR, os.path.basename(f.filename)))
    return jsonify({'success': True, 'message': '✅ 업로드 완료!'})

@app.route('/teacher/delete_file/<path:filename>', methods=['POST'])
def del_file(filename):
    p = os.path.join(SHARED_DIR, os.path.basename(filename))
    if os.path.exists(p): os.remove(p)
    return jsonify({'success': True, 'message': '삭제 완료'})

# ════════════════════════════════════════
#  교사: 문제 목록 CRUD 및 정답 검증 API
# ════════════════════════════════════════
@app.route('/api/<ptype>')
def get_probs(ptype):
    return jsonify(load_problems(PROBLEMS_FILE if ptype == 'problems' else EXAM_PROBLEMS_FILE))

@app.route('/api/<ptype>/add', methods=['POST'])
def add_prob(ptype):
    fpath = PROBLEMS_FILE if ptype == 'problems' else EXAM_PROBLEMS_FILE
    probs = load_problems(fpath)
    probs.append({
        'id': max((p['id'] for p in probs), default=0) + 1, 
        'title': request.json.get('title', '').strip(),
        'category': request.json.get('category', '일반').strip() or '일반',
        'desc': request.json.get('desc', ''), 
        'initial_code': request.json.get('initial_code', ''), 
        'test_cases': request.json.get('test_cases', []),
        # 추가: 모범답안 및 비밀번호 저장
        'model_answer': request.json.get('model_answer', ''),
        'answer_password': request.json.get('answer_password', '')
    })
    save_problems(fpath, probs)
    return jsonify({'success': True, 'message': '✅ 저장되었습니다!'})

@app.route('/api/<ptype>/update/<int:pid>', methods=['POST'])
def upd_prob(ptype, pid):
    fpath = PROBLEMS_FILE if ptype == 'problems' else EXAM_PROBLEMS_FILE
    probs = load_problems(fpath)
    for p in probs:
        if p['id'] == pid:
            p.update({
                'title': request.json.get('title', '').strip(), 
                'category': request.json.get('category', '일반').strip() or '일반',
                'desc': request.json.get('desc', ''), 
                'initial_code': request.json.get('initial_code', ''), 
                'test_cases': request.json.get('test_cases', p.get('test_cases', [])),
                # 추가: 모범답안 및 비밀번호 업데이트
                'model_answer': request.json.get('model_answer', p.get('model_answer', '')),
                'answer_password': request.json.get('answer_password', p.get('answer_password', ''))
            })
            break
    save_problems(fpath, probs)
    return jsonify({'success': True, 'message': '✅ 수정되었습니다!'})

@app.route('/api/<ptype>/delete/<int:pid>', methods=['POST'])
def del_prob(ptype, pid):
    fpath = PROBLEMS_FILE if ptype == 'problems' else EXAM_PROBLEMS_FILE
    save_problems(fpath, [p for p in load_problems(fpath) if p['id'] != pid])
    return jsonify({'success': True, 'message': '🗑 삭제되었습니다.'})

@app.route('/api/<ptype>/reorder', methods=['POST'])
def reorder_prob(ptype):
    fpath = PROBLEMS_FILE if ptype == 'problems' else EXAM_PROBLEMS_FILE
    new_order_ids = request.json.get('new_order', [])
    probs = load_problems(fpath)
    prob_dict = {p['id']: p for p in probs}
    reordered = []
    for pid in new_order_ids:
        if pid in prob_dict:
            reordered.append(prob_dict[pid])
            del prob_dict[pid]
    reordered.extend(prob_dict.values())
    save_problems(fpath, reordered)
    return jsonify({'success': True})

# --- 추가된 학생 모범답안 검증 API ---
@app.route('/api/verify_answer', methods=['POST'])
def verify_answer():
    data = request.json
    pid = data.get('problem_id')
    pwd = data.get('password', '')
    
    if pid == 'exam':
        return jsonify({'success': False, 'message': '수행평가는 모범 답안을 제공하지 않습니다.'})
        
    probs = load_problems(PROBLEMS_FILE)
    for p in probs:
        if str(p['id']) == str(pid):
            if not p.get('model_answer'):
                return jsonify({'success': False, 'message': '이 문제에는 등록된 모범 답안이 없습니다.'})
            if not p.get('answer_password'):
                return jsonify({'success': False, 'message': '비밀번호가 설정되어 있지 않습니다.'})
            if p.get('answer_password') == pwd:
                return jsonify({'success': True, 'model_answer': p.get('model_answer')})
            else:
                return jsonify({'success': False, 'message': '비밀번호가 틀렸습니다.'})
                
    return jsonify({'success': False, 'message': '문제를 찾을 수 없습니다.'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)