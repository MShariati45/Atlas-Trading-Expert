from pathlib import Path


def test_v02434_runtime_default_is_observation_only():
    text = Path('run_supervised_demo_runtime.py').read_text(encoding='utf-8')
    assert 'ap.add_argument("--allow-execution"' in text
    assert 'execution_enabled=bool(args.allow_execution)' in text
    assert 'SLIPPAGE_EXECUTION_COSTS_NOT_VALIDATED' in text
    assert 'DemoExecutionRuntime' in text


def test_v02434_no_enabled_unlock_shipped():
    assert not Path('runtime/DEMO_EXECUTION_ENABLE.json').exists()
    example = Path('DEMO_EXECUTION_ENABLE.example.json').read_text(encoding='utf-8')
    assert '"enabled": false' in example


def test_v02434_runbook_preserves_legal_mutation_paths():
    text = Path('SUPERVISED_DEMO_RUNTIME_RUNBOOK_v0.24.34.md').read_text(encoding='utf-8')
    assert 'ControlledDemoExecutionGate -> DemoOnlyMT5Transport' in text
    assert 'SupervisedDemoManagementGate -> DemoOnlyTradeManagementTransport' in text
    assert 'REAL/LIVE accounts remain forbidden' in text
