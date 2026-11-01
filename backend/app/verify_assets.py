from pathlib import Path

root = Path(__file__).parents[1] / "static"
assert (root / "index.html").is_file(), "Frontend build missing"
assert list((root / "assets").glob("*.js")), "JavaScript bundle missing"
assert list((root / "assets").glob("*.css")), "Stylesheet missing"
assert "Aurora" in (root / "index.html").read_text(), "Wrong frontend"
print("Frontend assets verified.")
