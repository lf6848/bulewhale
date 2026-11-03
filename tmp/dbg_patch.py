import re, shutil, time

base = "/opt/astrbot/data/plugins/astrbot_plugin_memory_system"
stamp = time.strftime("%Y%m%d-%H%M%S")
for f in ("main.py", "core/extractor.py"):
    shutil.copy(f"{base}/{f}", f"{base}/{f}.bak-{stamp}")

# 1) main.py: 确认钩子有没有被调用
p = f"{base}/main.py"
s = open(p, encoding="utf-8").read()
needle = '''            user_id = self.adapter.get_user_id(event)
            session_id = self.adapter.get_session_id(event)
            self._spawn(
                self.extractor.extract_and_store(user_id, session_id, user_text, assistant_text)
            )'''
repl = '''            user_id = self.adapter.get_user_id(event)
            session_id = self.adapter.get_session_id(event)
            logger.info(
                "[DBG] on_llm_response 触发 user=%s session=%s user_len=%d assistant_len=%d",
                user_id, session_id, len(user_text), len(assistant_text),
            )
            self._spawn(
                self.extractor.extract_and_store(user_id, session_id, user_text, assistant_text)
            )'''
assert needle in s, "main.py 未匹配"
s = s.replace(needle, repl)
open(p, "w", encoding="utf-8").write(s)

# 2) extractor.py: 打印 LLM 原始输出与解析结果
p2 = f"{base}/core/extractor.py"
s2 = open(p2, encoding="utf-8").read()
needle2 = '''            items = self._parse_result(raw)'''
repl2 = '''            logger.info("[DBG] 提取原始输出 len=%d: %s", len(raw), (raw or "")[:200].replace("\\n", " "))
            items = self._parse_result(raw)
            logger.info("[DBG] 解析条目=%d (阈值 %.2f)", len(items), self._importance_threshold)'''
assert needle2 in s2, "extractor.py 未匹配"
s2 = s2.replace(needle2, repl2, 1)
open(p2, "w", encoding="utf-8").write(s2)

print("patched", stamp)
