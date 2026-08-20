import asyncio, time, os

async def capture_dom_during_generation(page, out_dir="dom_captures"):
    os.makedirs(out_dir, exist_ok=True)
    start = time.time()
    i = 0
    # Poll fast (every 150ms) for ~6 seconds — covers most generations
    while time.time() - start < 6:
        try:
            # Scope to main content, not the whole page — cuts noise a lot
            html = await page.locator("main").evaluate("el => el.outerHTML")
        except Exception as e:
            html = f"<!-- capture failed: {e} -->"
        path = os.path.join(out_dir, f"snapshot_{i:03d}_{time.time()-start:.2f}s.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        i += 1
        await asyncio.sleep(0.15)