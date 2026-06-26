"""批量生成兑换码（CDKey），用于在第三方发卡平台自动发货。

用法（项目根目录，激活 venv 后）：
  python -m webapp.gen_cdkeys <页数> <数量> [批次备注]

示例：
  python -m webapp.gen_cdkeys 300 100 taobao0626   # 生成 100 个、每个 300 页的码
  python -m webapp.gen_cdkeys 1000 50              # 生成 50 个、每个 1000 页的码

输出：每行一个兑换码，直接复制粘贴到发卡平台的卡密库存即可。
"""
import sys
import secrets

from . import db

# 去掉易混淆字符（0/O/1/I）的码字母表
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gen_code():
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    try:
        pages = int(sys.argv[1])
        count = int(sys.argv[2])
    except ValueError:
        print("✗ 页数和数量必须是整数")
        sys.exit(1)
    batch = sys.argv[3] if len(sys.argv) > 3 else None

    db.init_db()
    made = []
    while len(made) < count:
        code = gen_code()
        if db.create_cdkey(code, pages, batch):
            made.append(code)

    # 纯码列表（供发卡平台导入）
    for code in made:
        print(code)

    sys.stderr.write(f"\n✓ 已生成 {len(made)} 个兑换码，每个 {pages} 页"
                     + (f"（批次 {batch}）" if batch else "") + "\n")


if __name__ == "__main__":
    main()
