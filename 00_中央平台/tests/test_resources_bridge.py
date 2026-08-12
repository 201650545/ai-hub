# -*- coding: utf-8 -*-
"""resources_bridge 针对性测试组（GPT 审阅第 6 步的 8+ 场景）。

零依赖：标准库 unittest + httpx.MockTransport（httpx 为项目既有依赖）。
运行：cd 00_中央平台 && python -m unittest tests.test_resources_bridge -v
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resources_bridge


def make_index(**kw):
    d = {
        "site": "test-site",
        "repo": "test/repo",
        "bridge_version": 1,
        "build_id": "build-A",
        "generated_at": "2026-08-11T00:00:00+00:00",
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


class TestFetchRemoteBuildConsistency(unittest.TestCase):
    """用 httpx.MockTransport 直接测 _fetch_remote 的双读 index 一致性。"""

    def _remote(self, handler):
        transport = httpx.MockTransport(handler)
        return patch.object(
            resources_bridge.httpx, "AsyncClient",
            return_value=httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(8.0), follow_redirects=True),
        )

    # 8. build_id 不一致（发布切换瞬间）→ 双读拒绝，返回全 None（触发回退）
    def test_build_id_mismatch_rejected(self):
        seen = {"index": 0}

        def handler(request):
            path = request.url.path
            if path.endswith("index.json"):
                seen["index"] += 1
                return httpx.Response(200, json=make_index(build_id="build-A" if seen["index"] == 1 else "build-B"))
            if path.endswith("capabilities.json"):
                return httpx.Response(200, json=make_caps())
            if path.endswith("instances.json"):
                return httpx.Response(200, json=make_insts())
            return httpx.Response(404)

        with self._remote(handler):
            files = run(resources_bridge._fetch_remote())
        self.assertIsNone(files["index.json"])  # 双读不一致 → 整体拒绝
        self.assertIsNone(files["capabilities.json"])
        self.assertIsNone(files["instances.json"])

    # build_id 一致 → 接受，返回三个文件
    def test_build_id_match_accepted(self):
        def handler(request):
            path = request.url.path
            if path.endswith("index.json"):
                return httpx.Response(200, json=make_index(build_id="build-A"))
            if path.endswith("capabilities.json"):
                return httpx.Response(200, json=make_caps())
            if path.endswith("instances.json"):
                return httpx.Response(200, json=make_insts())
            return httpx.Response(404)

        with self._remote(handler):
            files = run(resources_bridge._fetch_remote())
        self.assertEqual(files["index.json"]["build_id"], "build-A")
        self.assertEqual(len(files["capabilities.json"]), 2)
        self.assertEqual(len(files["instances.json"]), 2)


if __name__ == "__main__":
    unittest.main()
