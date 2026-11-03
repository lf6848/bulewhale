from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register


@register("zz_toolprobe", "dsh", "临时探针：打印每次请求实际携带的工具数量与名称", "v0.0.1")
class ToolProbe(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context, config)

    @filter.on_llm_request()
    async def probe(self, event, req):
        try:
            names = []
            ts = getattr(req, "func_tool", None)
            if ts is not None:
                names = [getattr(t, "name", "?") for t in getattr(ts, "tools", [])]
            logger.info(
                "[探针] 工具数=%d 名单=%s | 消息=%r",
                len(names), ",".join(names)[:300], (event.message_str or "")[:30],
            )
        except Exception:
            logger.exception("[探针] 失败")
