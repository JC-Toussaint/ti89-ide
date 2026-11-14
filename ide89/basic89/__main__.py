"""python -m basic89 program.b89  ->  program.b89.c"""
import sys
from .compiler import compile_file, CompileError

if len(sys.argv) != 2:
    sys.exit("usage: python -m basic89 program.b89")
try:
    print(compile_file(sys.argv[1]))
except CompileError as e:
    sys.exit(f"{sys.argv[1]}:{e.line}: error: {e.msg}")
