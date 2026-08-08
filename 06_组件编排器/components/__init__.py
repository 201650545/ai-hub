# -*- coding: utf-8 -*-
"""组件编排器 —— 组件包
每个组件模块暴露 `run(slot, rule_card_path) -> {"ok", "asset", "error"}`，
由编排器 orchestrator.py 按槽位 type 路由调用。
"""