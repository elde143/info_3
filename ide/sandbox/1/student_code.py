import builtins
_o = builtins.open
def _u(*a, **k):
    if 'encoding' not in k: k['encoding']='utf-8'
    return _o(*a, **k)
builtins.open = _u
n = int(input())
print(10 / n)