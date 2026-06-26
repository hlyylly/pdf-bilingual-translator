"""手动充值页数包（在线支付接入前，收到款后给账号加页数）。

用法（项目根目录，激活 venv 后）：
  python -m webapp.grant_credits <用户名> <页数>     # 加页数，如 300 / 1000
  python -m webapp.grant_credits <用户名> -100        # 也可扣减
  python -m webapp.grant_credits <用户名>              # 只查询当前余额
"""
import sys

from . import db


def main():
    db.init_db()
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    username = sys.argv[1]
    user = db.get_user_by_name(username)
    if not user:
        print(f"✗ 用户不存在：{username}")
        sys.exit(1)

    if len(sys.argv) == 2:
        print(f"{username} 当前页数包余额：{db.get_credits(user['id'])} 页")
        return

    try:
        delta = int(sys.argv[2])
    except ValueError:
        print(f"✗ 页数必须是整数：{sys.argv[2]}")
        sys.exit(1)

    new_balance = db.add_credits(user["id"], delta)
    sign = "+" if delta >= 0 else ""
    print(f"✓ {username} 充值 {sign}{delta} 页，当前余额：{new_balance} 页")


if __name__ == "__main__":
    main()
