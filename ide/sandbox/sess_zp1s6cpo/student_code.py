import builtins
_o = builtins.open
def _u(*a, **k):
    if 'encoding' not in k: k['encoding']='utf-8'
    return _o(*a, **k)
builtins.open = _u
color = input()
fruit = input()
print(color, fruit)