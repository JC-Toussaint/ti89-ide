# Environment for the GCC4TI command-line tools. Usage:  source gcc4ti-env.sh
_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export TIGCC="$_here/gcc4ti"
export PATH="$TIGCC/bin:$PATH"
unset _here
