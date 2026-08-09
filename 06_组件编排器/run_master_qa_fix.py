# -*- coding: utf-8 -*-
"""
Master OpenCLI AI Gateway Diagnostics & Autonomous Tester Command Script
========================================================================
Run command: python run_master_qa_fix.py
"""

import os
import sys
import time
import json

BASE_DIR = r"d:\项目\02_网关实例\ds_v4_cli"
sys.path.insert(0, BASE_DIR)

import engines
import probe_runner

ENGINES_LIST = ["yuanbao", "doubao", "kimi", "qianwen", "grok", "zai"]
TEST_PROMPT = "2026年最新AI技术趋势有哪些？请用简短3点总结"

def diagnose_engine(eid):
    eng = engines.ENGINES[eid]
    print(f"\n==================== [DIAGNOSIS] {eng['name']} ({eid}) ====================")
    
    # 1. Health check
    h = engines.engine_health(eid)
    print(f"Health Check: connected={h['connected']}, url={h.get('url')}, input_found={h.get('input_found')}")
    
    # 2. Extract DOM snippet
    ext = engines.extract_answer(eid, eng)
    print(f"Current DOM Extract: found={ext.get('found')}, text_len={len(ext.get('answer',''))}, snippet={repr(ext.get('answer','')[:120])}")
    
    return {"id": eid, "health": h, "extract": ext}

if __name__ == "__main__":
    print("🚀 Starting Master OpenCLI Gateway Engine Diagnostics...\n")
    results = {}
    for eid in ENGINES_LIST:
        results[eid] = diagnose_engine(eid)
        
    print("\n==================== SUMMARY REPORT ====================")
    for eid, data in results.items():
        ext = data["extract"]
        status = "✅ PASS" if (ext.get("found") and len(ext.get("answer","")) > 100) else "❌ FAIL"
        print(f"[{status}] {engines.ENGINES[eid]['name']} ({eid}): len={len(ext.get('answer',''))}")
