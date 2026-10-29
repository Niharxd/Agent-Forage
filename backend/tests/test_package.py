def test_backend_package_imports() -> None:
    import agentforge

    assert agentforge.__doc__ == "AgentForge backend package."
