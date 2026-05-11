import json, glob, os
os.chdir(os.path.expanduser("~/AI-Driven-Market-Digital-Twins/Perception/Tesla/parsed_output"))

# Check chart_extractions
chart_files = sorted(glob.glob("chart_extractions/*/*_charts.json"))
print("=== CHART EXTRACTIONS SAMPLE ===")
print("Total files:", len(chart_files))

with open(chart_files[0]) as f:
    data = json.load(f)
print("File:", chart_files[0])
print("Charts:", len(data))
print("First desc (300 chars):")
print(data[0]["description"][:300])
print()
print("--- Check for remaining Chinese ---")
chinese_count = 0
for cf in chart_files:
    with open(cf) as f:
        charts = json.load(f)
    for c in charts:
        desc = c.get("description", "")
        if desc:
            ascii_ratio = sum(1 for ch in desc if ord(ch) < 128) / max(len(desc), 1)
            if ascii_ratio < 0.8:
                chinese_count += 1
print("Descriptions still with Chinese:", chinese_count)
print()

# Check structured_data
struct_files = sorted(glob.glob("structured_data/*_structured.json"))
struct_files = [f for f in struct_files if "all_" not in f]
print("=== STRUCTURED DATA SAMPLE ===")
print("Total files:", len(struct_files))

with open(struct_files[0]) as f:
    sdata = json.load(f)
cats = sdata.get("chart_data", {}).get("categorized_charts", {})
for cat, items in list(cats.items())[:1]:
    print("Category:", cat)
    if items:
        print("First desc (300 chars):")
        print(items[0]["description"][:300])

print()
print("--- Check structured for remaining Chinese ---")
chinese_count2 = 0
for sf in struct_files:
    with open(sf) as f:
        sd = json.load(f)
    cats2 = sd.get("chart_data", {}).get("categorized_charts", {})
    for cat, items in cats2.items():
        if not isinstance(items, list):
            continue
        for item in items:
            desc = item.get("description", "")
            if desc:
                ascii_ratio = sum(1 for ch in desc if ord(ch) < 128) / max(len(desc), 1)
                if ascii_ratio < 0.8:
                    chinese_count2 += 1
print("Descriptions still with Chinese:", chinese_count2)
print()
print("=== VERIFICATION COMPLETE ===")
