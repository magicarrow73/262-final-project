import importlib, inspect
ft = importlib.import_module("system_main.ft_client_grpc")

def test_ft_client_exports_send_helpers():
    for fn in ("create_user", "start_auction", "submit_bid"):
        assert hasattr(ft, fn)
        assert callable(getattr(ft, fn))
        assert len(inspect.signature(getattr(ft, fn)).parameters) >= 2
