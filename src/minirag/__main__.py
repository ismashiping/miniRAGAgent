"""``python -m minirag`` 的进程入口。

只把 ``cli.main`` 的返回值交给解释器。导入本模块不会解析命令，也不会调用模型。
"""

import sys

from minirag.cli import main

if __name__ == "__main__":
    sys.exit(main())
