# -*- coding: utf-8 -*-
"""resource_config（网关侧 P4.2 消费者）单元测试。

覆盖：无配置放行 / 配对级 gating / 逗号模型变体 / expiry / last-good 回落 /
非法生成物拒绝 / limits shadow+external / capabilities static+external+矩阵门 /
status 无泄漏 / 与 api_gateway·rate_limit·capabilities 挂载点联动（stub 注入）。

运行: python tests/test_resource_config.py
（全程使用临时目录 env，绝不触碰 D:\\项目\\data\\search_gateway 真实文件）
"""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest

SG_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "services", "search_gateway"))
sys.path.insert(0, SG_DIR)


def make_resource(**overrides):
    r = {
        "resource_id": "res-test-001",
        "display_name": "测试资源",
        "channel": "stubchan",
        "unified_model": "stub-model",
        "upstream_model": "stub-upstream",
        "status": "active",
        "priority": 50,
        "expiry_at": None,
        "limits": {"rpm": None, "rpd": None, "concurrency": None},
        "capabilities": {"tools": "unknown", "vision": "unknown", "json_schema": "unknown"},
        "credential_ref": "cred:acc-stub-1",
        "notes": "unit",
    }
    r.update(overrides)
    return r


def make_art(resources, **top):
    doc = {
        "schema_version": 1,
        "generation_id": "gen-test-0001",
        "generated_at": "2026-08-29T12:00:00+08:00",
        "canonical_sha256": "0" * 64,
        "source": {"tables": {}},
        "limits_precedence": "shadow",
        "capabilities_precedence": "static",
        "resources": resources,
    }
    doc.update(top)
    return doc


class ResourceConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p42ut_")
        os.environ["RESOURCE_CONFIG_FILE"] = os.path.join(self.tmp, "gateway_resources.json")
        os.environ["RESOURCE_CONFIG_LAST_GOOD"] = os.path.join(self.tmp, "lg.json")
        os.environ["RESOURCE_CONFIG_LOG"] = os.path.join(self.tmp, "log.jsonl")
        import resource_config
        self.rc = importlib.reload(resource_config)

    def tearDown(self):
        pass

    # ---------- helpers ----------

    def write_live(self, doc, raw=None):
        p = os.path.join(self.tmp, "gateway_resources.json")
        with open(p, "wb") as f:
            f.write(raw if raw is not None else
                    json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        return p

    # ---------- 场景 ----------

    def test_01_no_config_passthrough(self):
        st = self.rc.status_payload()
        self.assertIsNone(st["active_generation_id"])
        self.assertEqual(st["last_reload_status"], "no_file")
        self.assertEqual(st["resource_count"], 0)
        self.assertIsNone(self.rc.channel_block("any", "thing"))
        self.assertIsNone(self.rc.external_policy("any"))
        self.assertIsNone(self.rc.external_capabilities("any", "thing"))

    def test_02_pair_gating(self):
        self.write_live(make_art([
            make_resource(status="paused"),
            make_resource(resource_id="res-test-002", channel="stubchan",
                          unified_model="live-model", status="active"),
        ]))
        blk = self.rc.channel_block("stubchan", "stub-model")
        self.assertEqual(blk, ("resource_paused", "res-test-001"))
        # 配对级精确：未覆盖的模型/渠道一律放行
        self.assertIsNone(self.rc.channel_block("stubchan", "other-model"))
        self.assertIsNone(self.rc.channel_block("other-chan", "stub-model"))
        # active 配对放行
        self.assertIsNone(self.rc.channel_block("stubchan", "live-model"))
        st = self.rc.status_payload()
        self.assertEqual(st["last_reload_status"], "ok")
        self.assertEqual(st["active_generation_id"], "gen-test-0001")
        self.assertEqual(st["resource_count"], 2)

    def test_03_comma_unified_model(self):
        self.write_live(make_art([
            make_resource(unified_model="m-a, m-b", status="disabled"),
        ]))
        self.assertEqual(self.rc.channel_block("stubchan", "m-a"),
                         ("resource_disabled", "res-test-001"))
        self.assertEqual(self.rc.channel_block("stubchan", "m-b"),
                         ("resource_disabled", "res-test-001"))

    def test_04_expiry(self):
        self.write_live(make_art([
            make_resource(resource_id="r-expired", unified_model="m-exp",
                          expiry_at="2020-01-01"),
            make_resource(resource_id="r-future", unified_model="m-fut",
                          expiry_at="2099-12-31"),
            make_resource(resource_id="r-iso", unified_model="m-iso",
                          status="active", expiry_at="2020-01-01T00:00:00+08:00"),
            make_resource(resource_id="r-today", unified_model="m-today",
                          expiry_at="2999-12-31"),
        ]))
        self.assertEqual(self.rc.channel_block("stubchan", "m-exp"),
                         ("resource_expired", "r-expired"))
        self.assertIsNone(self.rc.channel_block("stubchan", "m-fut"))
        self.assertEqual(self.rc.channel_block("stubchan", "m-iso"),
                         ("resource_expired", "r-iso"))
        self.assertIsNone(self.rc.channel_block("stubchan", "m-today"))

    def test_05_block_priority(self):
        # 同一配对两个非 active 资源：disabled 优先于 paused（_BLOCK_PRIORITY 顺序）
        self.write_live(make_art([
            make_resource(resource_id="r-paused", status="paused"),
            make_resource(resource_id="r-disabled", status="disabled"),
        ]))
        self.assertEqual(self.rc.channel_block("stubchan", "stub-model"),
                         ("resource_disabled", "r-disabled"))

    def test_06_last_good_on_corrupt(self):
        self.write_live(make_art([make_resource(status="paused")]))
        self.assertEqual(self.rc.channel_block("stubchan", "stub-model")[0],
                         "resource_paused")
        # live 变非法 JSON → 保持 last-good 判定，meta 记 failed
        self.write_live(None, raw=b'{"broken":')
        self.assertEqual(self.rc.channel_block("stubchan", "stub-model")[0],
                         "resource_paused")
        st = self.rc.status_payload()
        self.assertEqual(st["last_reload_status"], "failed")
        self.assertGreaterEqual(st["fail_count"], 1)
        self.assertEqual(st["active_generation_id"], "gen-test-0001")

    def test_07_last_good_on_missing(self):
        self.write_live(make_art([make_resource(status="paused")]))
        self.rc.channel_block("stubchan", "stub-model")
        os.unlink(os.path.join(self.tmp, "gateway_resources.json"))
        self.assertEqual(self.rc.channel_block("stubchan", "stub-model")[0],
                         "resource_paused")
        st = self.rc.status_payload()
        self.assertEqual(st["last_reload_status"], "failed")
        self.assertEqual(st["active_generation_id"], "gen-test-0001")

    def test_08_invalid_artifacts_rejected(self):
        cases = [
            ("schema_version", make_art([make_resource()], schema_version=99)),
            ("dup_rid", make_art([make_resource(), make_resource()])),
            ("bad_status", make_art([make_resource(status="weird")])),
            ("bad_limits_type", make_art([make_resource(limits="30")])),
            ("bad_caps_state", make_art([make_resource(
                capabilities={"tools": "maybe", "vision": "unknown", "json_schema": "unknown"})])),
            ("bad_cred", make_art([make_resource(credential_ref="sk-live-key-123")])),
            ("bad_expiry", make_art([make_resource(expiry_at="yesterday")])),
        ]
        for tag, doc in cases:
            self.write_live(doc)
            st = self.rc.status_payload()
            self.assertEqual(st["last_reload_status"], "failed",
                             "case %s 应拒绝" % tag)
            self.assertIn("二次校验失败", st["last_reload_error"] or "")
            self.assertIsNone(self.rc.channel_block("stubchan", "stub-model"),
                              "case %s 无 last-good → 放行且无快照" % tag)
        # secret 扫描：sk- 形态 token 出现在自由文本里也拒绝
        self.write_live(make_art([make_resource(notes="key=sk-abcdefghijklmnopqrstu")]))
        self.assertEqual(self.rc.status_payload()["last_reload_status"], "failed")

    def test_09_limits_shadow_default(self):
        self.write_live(make_art([
            make_resource(status="active", limits={"rpm": 30, "rpd": None, "concurrency": None}),
        ]))
        self.assertIsNone(self.rc.external_policy("stubchan"),
                          "shadow 模式 external_policy 必须返回 None")
        # 差异记录落日志（legacy 无 stubchan 规则 → differs）
        self.rc.external_policy("stubchan")
        log = io.open(os.path.join(self.tmp, "log.jsonl"), encoding="utf-8").read()
        self.assertIn("limits_shadow_differs", log)

    def test_10_limits_external_min_agg(self):
        self.write_live(make_art([
            make_resource(resource_id="r-30", status="active",
                          limits={"rpm": 30, "rpd": None, "concurrency": None}),
            make_resource(resource_id="r-10", unified_model="m-2", status="active",
                          limits={"rpm": 10, "rpd": 100, "concurrency": None}),
        ], limits_precedence="external"))
        pol = self.rc.external_policy("stubchan")
        self.assertIsNotNone(pol)
        self.assertEqual(pol["scope"], "channel")
        rules = {r["window"]: r["limit"] for r in pol["rules"]}
        self.assertEqual(rules[60], 10)    # 渠道级取最严
        self.assertEqual(rules[86400], 100)
        self.assertTrue(all(r["source"] == "control_plane" for r in pol["rules"]))
        # 全 paused / 无 limits → None（与无静态规则渠道行为一致）
        self.assertIsNone(self.rc.external_policy("empty-chan"))

    def test_11_capabilities_static_default(self):
        self.write_live(make_art([
            make_resource(status="active",
                          capabilities={"tools": "supported", "vision": "unsupported",
                                        "json_schema": "unknown"}),
        ]))
        self.assertIsNone(self.rc.external_capabilities("stubchan", "stub-model"))
        self.assertIsNone(self.rc.external_capabilities("stubchan", "uncovered"))

    def test_12_capabilities_external_with_matrix_gate(self):
        import capabilities as cap_mod
        orig_loader = cap_mod.load_model_capabilities
        try:
            # 静态表声明 stubchan/stub-model 三键与生成物完全一致 → external 生效
            cap_mod.load_model_capabilities = lambda: {
                "version": 1, "channels": {"stubchan": {"models": {
                    "stub-model": {"tools": True, "vision": False, "json_schema": None}}}}}
            self.write_live(make_art([
                make_resource(status="active",
                              capabilities={"tools": "supported", "vision": "unsupported",
                                            "json_schema": "unknown"}),
            ], capabilities_precedence="external"))
            ext = self.rc.external_capabilities("stubchan", "stub-model")
            self.assertIsNotNone(ext)
            self.assertTrue(ext["known"])
            self.assertEqual(ext["source"], "control_plane")
            self.assertEqual(ext["capabilities"]["tools"], True)
            self.assertEqual(ext["capabilities"]["vision"], False)
            self.assertIsNone(ext["capabilities"]["json_schema"])

            # 矩阵冲突（tools 不一致）→ 拒绝切换，external_capabilities 回 None
            self.write_live(make_art([
                make_resource(status="active",
                              capabilities={"tools": "unsupported", "vision": "unknown",
                                            "json_schema": "unknown"}),
            ], generation_id="gen-test-0002", capabilities_precedence="external"))
            self.assertIsNone(self.rc.external_capabilities("stubchan", "stub-model"))
            st = self.rc.status_payload()
            self.assertEqual(st["capabilities_precedence"], "static")
            self.assertIn("tools", st.get("capabilities_refused_reason") or "")
        finally:
            cap_mod.load_model_capabilities = orig_loader

    def test_13_status_payload_no_secret_leak(self):
        self.write_live(make_art([make_resource()]))
        self.rc.channel_block("stubchan", "stub-model")
        st = self.rc.status_payload()
        self.assertNotIn("resources", st)
        dumped = json.dumps(st, ensure_ascii=False)
        self.assertNotIn("cred:acc-stub-1", dumped)
        self.assertIn("credential_refs", dumped)  # 只有计数，无具体 ref
        # 终审 D2：口径必须显式声明为渠道名映射，禁止 resolved 误导性命名
        self.assertIn("semantics", st["credential_refs"])
        self.assertEqual(st["credential_refs"]["semantics"], "channel_name_mapped")
        self.assertIn("mapped", st["credential_refs"])
        self.assertIn("unmapped", st["credential_refs"])
        self.assertNotIn("resolved", dumped)
        self.assertEqual(st["credential_refs"]["mapped"], 0)     # stubchan 非真渠道
        self.assertEqual(st["credential_refs"]["unmapped"], 1)
        self.assertIn("active_generation_id", dumped)
        self.assertIn("active_sha256", dumped)

    def test_14_hot_reload_generation_swap(self):
        self.write_live(make_art([make_resource(status="paused")],
                                 generation_id="gen-a"))
        self.assertEqual(self.rc.channel_block("stubchan", "stub-model")[0],
                         "resource_paused")
        # 原子换新：paused → active 后同进程立即生效（无需重启）
        self.write_live(make_art([make_resource(status="active")],
                                 generation_id="gen-b"))
        self.assertIsNone(self.rc.channel_block("stubchan", "stub-model"))
        st = self.rc.status_payload()
        self.assertEqual(st["active_generation_id"], "gen-b")
        self.assertGreaterEqual(st["reload_count"], 2)

    def test_15_api_gateway_hook(self):
        """挂载点联动：client 名优先、上游名兜底、模块缺失放行、异常放行。"""
        import api_gateway as ag
        self.write_live(make_art([
            make_resource(unified_model="client-name", status="paused"),
        ]))
        real = ag._rcfg
        try:
            ag._rcfg = self.rc
            self.assertEqual(ag._resource_block("stubchan", "client-name"),
                             ("resource_paused", "res-test-001"))
            # 上游名兜底：资源表登记上游名、请求别名映射后的上游模型
            self.write_live(make_art([
                make_resource(unified_model="up-name-only", status="draining"),
            ]))
            self.assertEqual(ag._resource_block("stubchan", "client-alias", "up-name-only"),
                             ("resource_draining", "res-test-001"))
            # 未覆盖 → None
            self.assertIsNone(ag._resource_block("stubchan", "nope", "also-nope"))
            # 模块缺失 / 异常 → 放行
            ag._rcfg = None
            self.assertIsNone(ag._resource_block("stubchan", "client-name"))
            class Boom:
                def channel_block(self, *a):
                    raise RuntimeError("boom")
            ag._rcfg = Boom()
            self.assertIsNone(ag._resource_block("stubchan", "client-name"))
            self.assertIn("last_reload_status", ag._resource_status())
        finally:
            ag._rcfg = real

    def test_16_rate_limit_and_capabilities_hooks(self):
        import rate_limit as rl
        import capabilities as cp
        self.write_live(make_art([
            make_resource(status="active",
                          limits={"rpm": 5, "rpd": None, "concurrency": None}),
        ], limits_precedence="external", capabilities_precedence="external"))
        real_rl, real_cp = rl._rcfg, cp._rcfg
        orig_loader = cp.load_model_capabilities
        try:
            # 矩阵门需要静态表与生成物 100% 一致：mock 掉静态表避免真实表干扰
            cp.load_model_capabilities = lambda: {
                "version": 1, "channels": {"stubchan": {"models": {
                    "stub-model": {"tools": True, "vision": None, "json_schema": None}}}}}
            rl._rcfg = self.rc
            pol = rl._external_policy("stubchan")
            self.assertIsNotNone(pol)
            self.assertEqual(pol["scope"], "channel")
            bks = rl._resolve("stubchan", "stub-model", "k1")
            self.assertEqual(bks, [("stubchan", pol)])
            rl._rcfg = None
            self.assertIsNone(rl._external_policy("stubchan"))

            cp._rcfg = self.rc
            self.write_live(make_art([
                make_resource(status="active",
                              capabilities={"tools": "supported", "vision": "unknown",
                                            "json_schema": "unknown"}),
            ], generation_id="gen-caps-1", capabilities_precedence="external"))
            mc = cp.model_capabilities("stubchan", "stub-model")
            self.assertEqual(mc["source"], "control_plane")
            self.assertTrue(mc["known"])
            cp._rcfg = None
            self.assertIsNone(cp._external_capabilities("stubchan", "stub-model"))
        finally:
            rl._rcfg, cp._rcfg = real_rl, real_cp
            cp.load_model_capabilities = orig_loader


if __name__ == "__main__":
    unittest.main(verbosity=2)
