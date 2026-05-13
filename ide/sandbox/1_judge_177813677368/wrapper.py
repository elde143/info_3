import sys, time, tracemalloc, json, builtins
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
