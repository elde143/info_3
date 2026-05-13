import builtins
_o = builtins.open
def _u(*a, **k):
    if 'encoding' not in k: k['encoding']='utf-8'
    return _o(*a, **k)
builtins.open = _u
a = int(input())
b = int(input())
# 두 수의 합을 출력하세요.
print(a+b)