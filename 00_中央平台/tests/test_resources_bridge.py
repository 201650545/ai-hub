# -*- coding: utf-8 -*-
"""resources_bridge 针对性测试组（GPT 审阅第 6 步的 8+ 场景）。

零依赖：标准库 unittest + httpx.MockTransport（httpx 为项目既有依赖）。
运行：cd 00_中央平台 && python -m unittest tests.test_resources_bridge -v
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resources_bridge


def make_index(**kw):
    # generated_at 默认取「当前时刻」，避免硬编码日期随时间推移滑出新鲜窗口
    # （2026-08-11 的硬编码值导致 test_remote_ok 在 48h 后 fresh 恒为 False）。
    d = {
        "site": "test-site",
        "repo": "test/repo",
        "bridge_version": 1,
        "build_id": "build-A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "freshness": {"stale_after_hours": 48},
    }
    d.update(kw)
    return d


def make_caps(n=2):
    return [{"capability_id": f"c{i}", "资源名称": f"n{i}"} for i in range(n)]


def make_insts(n=2):
    return [{"instance_id": f"i{i}", "平台": "p"} for i in range(n)]


def run(coro):
    return asyncio.run(coro)


def async_fn(ret):
    async def _f(*a, **k):
        return ret
    return _f


def sync_fn(ret):
    def _f(*a, **k):
        return ret
    return _f


class TestGetResources(unittest.TestCase):
    """通过 patch _fetch_remote/_load_local 测 get_resources 的聚合/回退/校验逻辑。"""

    def setUp(self):
        # 重置模块级缓存，避免用例间污染
        resources_bridge._CACHE.update(ts=0.0, data=None, ttl=resources_bridge.CACHE_TTL)

    # 1. remote 全正常
    def test_remote_ok(self):
        files = {"index.json": make_index(), "capabilities.json": make_caps(21), "instances.json": make_insts(21)}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(files)), \
             patch.object(resources_bridge, "_load_local", new=sync_fn({})):
            data = run(resources_bridge.get_resources("remote"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "remote")
        self.assertFalse(data["fallback"])
        self.assertFalse(data["cache_hit"])
        self.assertEqual(data["counts"], {"capabilities": 21, "instances": 21})
        self.assertTrue(data["meta"]["fresh"])

    # 2. remote 单文件失败 + local 正常 → auto 原子回退 local
    def test_auto_fallback_local_on_single_file_failure(self):
        remote = {"index.json": make_index(), "capabilities.json": None, "instances.json": make_insts()}
        local = {"index.json": make_index(), "capabilities.json": make_caps(5), "instances.json": make_insts(6)}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(remote)), \
             patch.object(resources_bridge, "_load_local", new=sync_fn(local)):
            data = run(resources_bridge.get_resources("auto"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "local")
        self.assertTrue(data["fallback"])
        self.assertEqual(data["counts"], {"capabilities": 5, "instances": 6})

    # 3. remote 非法 JSON（结构错：capabilities 是 dict）→ 校验失败，不 500
    def test_remote_invalid_shape_rejected(self):
        remote = {"index.json": make_index(), "capabilities.json": {"oops": 1}, "instances.json": make_insts()}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(remote)), \
             patch.object(resources_bridge, "_load_local", new=sync_fn({})):
            data = run(resources_bridge.get_resources("remote"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "remote")

    # 4. local 缺文件 → 报错
    def test_local_missing_reports_error(self):
        local = {"index.json": make_index(), "capabilities.json": None, "instances.json": make_insts()}
        with patch.object(resources_bridge, "_load_local", new=sync_fn(local)):
            data = run(resources_bridge.get_resources("local"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "local")

    # 5. remote + local 双失败 → ok=False
    def test_both_fail(self):
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn({"index.json": None, "capabilities.json": None, "instances.json": None})), \
             patch.object(resources_bridge, "_load_local", new=sync_fn({"index.json": None, "capabilities.json": None, "instances.json": None})):
            data = run(resources_bridge.get_resources("auto"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["source"], "auto")

    # 6. 空数组是合法数据，不误判为拉取失败（_validate_files 用 isinstance 不判空）
    def test_empty_arrays_are_valid(self):
        remote = {"index.json": make_index(), "capabilities.json": [], "instances.json": []}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(remote)), \
             patch.object(resources_bridge, "_load_local", new=sync_fn({})):
            data = run(resources_bridge.get_resources("remote"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["counts"], {"capabilities": 0, "instances": 0})

    # 7. stale 数据 → fresh=False
    def test_stale_data_fresh_false(self):
        index = make_index(generated_at="2020-01-01T00:00:00+00:00")
        files = {"index.json": index, "capabilities.json": make_caps(), "instances.json": make_insts()}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(files)):
            data = run(resources_bridge.get_resources("remote"))
        self.assertIs(data["meta"]["fresh"], False)

    # 10. generated_at 无时区 → fresh=None（未知），不误判新鲜
    def test_naive_generated_at_fresh_none(self):
        index = make_index(generated_at="2026-08-11T00:00:00")
        files = {"index.json": index, "capabilities.json": make_caps(), "instances.json": make_insts()}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(files)):
            data = run(resources_bridge.get_resources("remote"))
        self.assertIsNone(data["meta"]["fresh"])

    # 缓存：命中时 fresh 动态重算 + cache_hit=True
    def test_cache_hit_recomputes_fresh(self):
        files = {"index.json": make_index(), "capabilities.json": make_caps(), "instances.json": make_insts()}
        with patch.object(resources_bridge, "_fetch_remote", new=async_fn(files)), \
             patch.object(resources_bridge, "_load_local", new=sync_fn({})):
            first = run(resources_bridge.get_resources("auto"))
            second = run(resources_bridge.get_resources("auto"))
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertIn("fresh", second["meta"])
        # 二次命中不得污染第一次已返回的对象（后端已改为返回拷贝）
        self.assertFalse(first["cache_hit"])


class TestFetchRemoteManifest(unittest.TestCase):
    """用 httpx.MockTransport 直接测 _fetch_remote 的 manifest 提交点校验（方案书 v2）。

    场景：全匹配接受 / 单文件哈希不匹配回退 / 无 manifest fail-closed /
          manifest 结构非法回退 / build_id 不一致拒绝。
    """

    def _transport(self, handler):
        return patch.object(
            resources_bridge.httpx, "AsyncClient",
            return_value=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                timeout=httpx.Timeout(8.0), follow_redirects=True),
        )

    def _route(self, files_bytes, manifest=None):
        def handler(request):
            name = request.url.path.rsplit("/", 1)[-1]
            if name == "manifest.json":
                if manifest is None:
                    return httpx.Response(404)  # 无 manifest
                return httpx.Response(200, json=manifest)
            if name in files_bytes:
                return httpx.Response(200, content=files_bytes[name])  # 原始字节
            return httpx.Response(404)
        return handler

    def _real_files(self):
        """返回 4 个真实字节文件 + 按字节算的 manifest（与 exporter 同口径）。"""
        index = make_index()
        schema = {"bridge_version": 1, "tables": {}}
        files_bytes = {
            "index.json": json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8"),
            "capabilities.json": json.dumps(make_caps(), ensure_ascii=False, indent=2).encode("utf-8"),
            "instances.json": json.dumps(make_insts(), ensure_ascii=False, indent=2).encode("utf-8"),
            "schema.json": json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"),
        }
        manifest = {
            "bridge_version": 1,
            "build_id": index["build_id"],
            "generated_at": index["generated_at"],
            "files": {n: {"sha256": hashlib.sha256(b).hexdigest()} for n, b in files_bytes.items()},
        }
        return files_bytes, manifest, index

    # 1. manifest 全匹配接受
    def test_manifest_all_match_accepted(self):
        files_bytes, manifest, index = self._real_files()
        with self._transport(self._route(files_bytes, manifest)):
            files = run(resources_bridge._fetch_remote())
        self.assertEqual(files["index.json"]["build_id"], index["build_id"])
        self.assertEqual(len(files["capabilities.json"]), 2)
        self.assertEqual(len(files["instances.json"]), 2)
        self.assertIn("schema.json", files)

    # 2. 单文件哈希不匹配（CDN 混搭）→ 整体回退，绝不接受
    def test_single_file_hash_mismatch_fails_closed(self):
        files_bytes, manifest, _ = self._real_files()
        files_bytes["capabilities.json"] = b'[{"tampered": true}]'  # 篡改字节
        with self._transport(self._route(files_bytes, manifest)):
            files = run(resources_bridge._fetch_remote())
        self.assertIsNone(files["index.json"])
        self.assertIsNone(files["capabilities.json"])
        self.assertIsNone(files["instances.json"])

    # 3. 无 manifest → fail-closed（硬切换，不降级双读）
    def test_no_manifest_fails_closed(self):
        files_bytes, _, _ = self._real_files()
        with self._transport(self._route(files_bytes, None)):
            files = run(resources_bridge._fetch_remote())
        self.assertIsNone(files["index.json"])
        self.assertIsNone(files["capabilities.json"])

    # 4. manifest 结构非法 → 回退
    def test_manifest_invalid_shape_fails_closed(self):
        files_bytes, manifest, _ = self._real_files()
        manifest.pop("files", None)  # 缺 files 声明
        with self._transport(self._route(files_bytes, manifest)):
            files = run(resources_bridge._fetch_remote())
        self.assertIsNone(files["index.json"])

    # 5. build_id 不一致（纵深断言）→ 拒绝
    def test_build_id_mismatch_rejected(self):
        files_bytes, manifest, _ = self._real_files()
        manifest["build_id"] = "other-build"  # 与 index.build_id 不一致
        with self._transport(self._route(files_bytes, manifest)):
            files = run(resources_bridge._fetch_remote())
        self.assertIsNone(files["index.json"])


class TestLoadLocalManifest(unittest.TestCase):
    """_load_local 的本地 manifest 校验（方案书 v2 §2.2）。"""

    def _files_bytes(self):
        index = make_index()
        schema = {"bridge_version": 1, "tables": {}}
        files_bytes = {
            "index.json": json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8"),
            "capabilities.json": json.dumps(make_caps(), ensure_ascii=False, indent=2).encode("utf-8"),
            "instances.json": json.dumps(make_insts(), ensure_ascii=False, indent=2).encode("utf-8"),
            "schema.json": json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"),
        }
        manifest = {
            "bridge_version": 1,
            "build_id": index["build_id"],
            "files": {n: {"sha256": hashlib.sha256(b).hexdigest()} for n, b in files_bytes.items()},
        }
        return files_bytes, manifest

    def _write_local(self, d, files_bytes, manifest):
        for n, b in files_bytes.items():
            with open(os.path.join(d, n), "wb") as f:
                f.write(b)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)

    # 本地 manifest + 文件字节匹配 → 接受
    def test_local_manifest_match_accepted(self):
        files_bytes, manifest = self._files_bytes()
        with tempfile.TemporaryDirectory() as d:
            self._write_local(d, files_bytes, manifest)
            with patch.object(resources_bridge, "LOCAL_DIR", Path(d)):
                out = resources_bridge._load_local()
        self.assertEqual(out["index.json"]["build_id"], "build-A")
        self.assertEqual(len(out["capabilities.json"]), 2)

    # 本地文件被篡改 → 该校验文件置 None（全有或全无由调用方判断）
    def test_local_manifest_tamper_detected(self):
        files_bytes, manifest = self._files_bytes()
        with tempfile.TemporaryDirectory() as d:
            self._write_local(d, files_bytes, manifest)
            with open(os.path.join(d, "capabilities.json"), "wb") as f:
                f.write(b'[{"tampered": true}]')
            with patch.object(resources_bridge, "LOCAL_DIR", Path(d)):
                out = resources_bridge._load_local()
        self.assertIsNone(out["capabilities.json"])

    # 本地无 manifest → 过渡期信任（三个月后删除该分支）
    def test_local_without_manifest_trusts_build(self):
        files_bytes, _ = self._files_bytes()
        with tempfile.TemporaryDirectory() as d:
            for n, b in files_bytes.items():
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b)
            with patch.object(resources_bridge, "LOCAL_DIR", Path(d)):
                out = resources_bridge._load_local()
        self.assertEqual(out["index.json"]["build_id"], "build-A")
        self.assertEqual(len(out["capabilities.json"]), 2)

    # 本地 manifest 存在但解析失败 → 整体不可信
    def test_local_manifest_unparseable_fails_closed(self):
        files_bytes, _ = self._files_bytes()
        with tempfile.TemporaryDirectory() as d:
            for n, b in files_bytes.items():
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b)
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                f.write("{broken json")
            with patch.object(resources_bridge, "LOCAL_DIR", Path(d)):
                out = resources_bridge._load_local()
        self.assertIsNone(out["index.json"])


def run_all():
    """供 tests/run_all.py 聚合调用：把本模块全部 unittest 用例转成 Result 列表。

    注意：本模块在 00_中央平台/tests/ 下，run_all.py 位于 tests/ 下；
    通过 importlib 加载时 sys.path 需包含本目录（见 run_all.py 注册处）。
    这里不 import common（避免路径耦合），直接用 unittest 结果自造 Result 结构。
    """
    import io

    # 惰性 import common（run_all.py 的 tests/ 在 sys.path 时可取；
    # 独立 unittest 运行时不走本函数，不受影响）
    try:
        from common import Result
    except ImportError:
        Result = type("_Result", (), {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP",
                                      "__init__": lambda self, n, s, d="": (setattr(self, "name", n),
                                                                              setattr(self, "status", s),
                                                                              setattr(self, "detail", d))})

    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    res = runner.run(suite)

    out = []
    if res.failures or res.errors:
        for test, tb in res.failures + res.errors:
            out.append(Result(f"资源数据桥: {test}", Result.FAIL,
                              tb.strip().splitlines()[-1] if tb.strip() else ""))
    else:
        out.append(Result("资源数据桥单测", Result.PASS, f"{res.testsRun} 用例全过"))
    return out


if __name__ == "__main__":
    unittest.main()
