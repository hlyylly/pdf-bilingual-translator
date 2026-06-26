"""微信支付 v3 · Native 扫码。封装 wechatpayv3 SDK，供下单/查询/回调使用。

参考服务器上 soft-copyright 项目的实现移植而来。Native 适合 PC/网页：
下单返回 code_url → 前端生成二维码 → 用户微信扫码付 → 轮询 query 或异步 notify 确认。
"""
import os
import json
import logging

from .settings import WECHAT_PAY, wechat_pay_ready

logger = logging.getLogger("wechatpay")
_instance = None


def get_pay():
    """惰性初始化并缓存 WeChatPay 实例；未配置好返回 None。"""
    global _instance
    if _instance is not None:
        return _instance
    if not wechat_pay_ready():
        return None
    try:
        from wechatpayv3 import WeChatPay, WeChatPayType
        key_path = os.path.join(WECHAT_PAY["cert_dir"], "apiclient_key.pem")
        with open(key_path) as f:
            private_key = f.read()
        _instance = WeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=WECHAT_PAY["mchid"],
            private_key=private_key,
            cert_serial_no=WECHAT_PAY["cert_serial_no"],
            apiv3_key=WECHAT_PAY["apiv3_key"],
            appid=WECHAT_PAY["appid"],
            notify_url=WECHAT_PAY["notify_url"],
            cert_dir=WECHAT_PAY["cert_dir"],
        )
        logger.info("微信支付 SDK 初始化成功 mchid=%s", WECHAT_PAY["mchid"])
        return _instance
    except ImportError:
        logger.warning("wechatpayv3 未安装")
        return None
    except Exception as e:
        logger.error("微信支付初始化失败: %s", e)
        return None


def create_native(out_trade_no, amount_fen, description, attach=""):
    """下单，返回 (code_url 或 None, 错误信息)。amount_fen 单位：分。"""
    pay = get_pay()
    if not pay:
        return None, "支付功能未配置"
    code, message = pay.pay(
        description=description,
        out_trade_no=out_trade_no,
        amount={"total": amount_fen},
        attach=attach,
        pay_type=_native_type(),
    )
    if code == 200:
        return json.loads(message).get("code_url"), ""
    logger.error("下单失败 %s: %s", code, message)
    return None, f"下单失败: {message}"


def query(out_trade_no):
    """查询订单交易状态，返回 (trade_state 或 None, transaction_id 或 None)。"""
    pay = get_pay()
    if not pay:
        return None, None
    code, message = pay.query(out_trade_no=out_trade_no)
    if code == 200:
        d = json.loads(message)
        return d.get("trade_state"), d.get("transaction_id")
    return None, None


def decode_callback(headers, body):
    """验签并解密回调；返回解密后的 dict（失败返回 None）。"""
    pay = get_pay()
    if not pay:
        return None
    try:
        return pay.callback(headers, body)
    except Exception as e:
        logger.error("回调验签失败: %s", e)
        return None


def _native_type():
    try:
        from wechatpayv3 import WeChatPayType
        return WeChatPayType.NATIVE
    except ImportError:
        return None
