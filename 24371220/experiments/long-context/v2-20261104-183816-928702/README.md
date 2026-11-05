# 材料路径迁移后的离线预检

本记录为 `preflight_only=true`，状态 `preflight_passed`，没有启动模型或正式评分。原始 protocol.json、材料哈希、源码基线、PDF 提取与完整性日志保留。源码基线退出码 1 是未实现题目功能时的结果，不是正式验收通过。

2026-11-05 清理：删除可由课程材料和 prepare.py 重新生成的 workspace/DeepInfer 工作副本；原始课程材料未改动。protocol.json 内历史路径和哈希保持原样。

同日对 main 的路径调整补查：tests/test_evaluation_launcher.py 共 8 项离线测试通过；run_public.sh 的 bash -n 检查通过。未重新运行付费评测。
