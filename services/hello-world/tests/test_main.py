from hello_world.main import main


def test_main(capsys):
    assert main() == 0
    captured = capsys.readouterr()
    assert "Hello, world!" in captured.out
