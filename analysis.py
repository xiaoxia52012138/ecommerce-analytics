"""
E-commerce Analytics — Online Retail II (UCI)
==============================================
End-to-end business analytics project on UK online-retail transactions
(Dec 2009 – Dec 2011).

Pipeline:
  1. Load & clean raw transactions
  2. Monthly revenue trend
  3. RFM customer segmentation
  4. Repeat-purchase rate & basket metrics
  5. Product-category analysis (keyword-derived categories)
  6. Geographic revenue analysis

Outputs: PNG figures in outputs/ + key findings printed to stdout.
"""

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------- config
BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "online_retail_II.xlsx"
OUT = BASE / "outputs"
OUT.mkdir(exist_ok=True)

sns.set_theme(style="whitegrid")
plt.rcParams.update({"figure.dpi": 150, "font.size": 10})

# ================================================================ 1. LOAD
print("Loading data ...")
sheets = pd.read_excel(DATA, sheet_name=None)          # two year-sheets
raw = pd.concat(sheets.values(), ignore_index=True)
raw = raw.rename(columns={
    "Invoice": "InvoiceNo", "Price": "UnitPrice", "Customer ID": "CustomerID",
})
print(f"  raw rows: {len(raw):,}  |  columns: {list(raw.columns)}")

# ================================================================ 2. CLEAN
df = raw.copy()

# 2a. drop exact duplicates
n0 = len(df)
df = df.drop_duplicates()
print(f"  duplicates removed: {n0 - len(df):,}")

# 2b. drop cancelled orders (InvoiceNo starting with 'C')
df["InvoiceNo"] = df["InvoiceNo"].astype(str)
n0 = len(df)
df = df[~df["InvoiceNo"].str.startswith("C")]
print(f"  cancelled orders removed: {n0 - len(df):,}")

# 2c. drop rows without a CustomerID (needed for customer-level analysis)
n0 = len(df)
df = df.dropna(subset=["CustomerID"])
print(f"  rows w/o CustomerID removed: {n0 - len(df):,}")

# 2d. drop non-positive quantities / prices (returns, data errors, freebies)
df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
df["UnitPrice"] = pd.to_numeric(df["UnitPrice"], errors="coerce")
n0 = len(df)
df = df[(df["Quantity"] > 0) & (df["UnitPrice"] > 0)]
print(f"  non-positive qty/price removed: {n0 - len(df):,}")

# 2e. drop non-product adjustment rows (postage, manual adjustments, discounts…)
NON_PRODUCT = {"POST", "M", "D", "DOT", "PADS", "BANK CHARGES",
               "AMAZONFEE", "AMAZON FEE", "CRUK"}
n0 = len(df)
df = df[~df["StockCode"].astype(str).str.upper().isin(NON_PRODUCT)]
df = df[~df["Description"].astype(str).str.upper().isin(
    {"MANUAL", "POSTAGE", "DOTCOM POSTAGE", "DISCOUNT", "BANK CHARGES"})]
print(f"  non-product rows removed: {n0 - len(df):,}")

# 2f. final types & revenue
df["CustomerID"] = df["CustomerID"].astype(int).astype(str)
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
df["Revenue"] = df["Quantity"] * df["UnitPrice"]

print(f"  clean rows: {len(df):,}")
print(f"  date range: {df['InvoiceDate'].min().date()} → {df['InvoiceDate'].max().date()}")
print(f"  customers: {df['CustomerID'].nunique():,}  |  orders: {df['InvoiceNo'].nunique():,}  "
      f"|  countries: {df['Country'].nunique()}")

TOTAL_REVENUE = df["Revenue"].sum()

# ================================================= 3. MONTHLY REVENUE TREND
monthly = (df.set_index("InvoiceDate")
             .resample("M")["Revenue"].sum()
             .rename_axis("Month").reset_index())

fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(monthly["Month"], monthly["Revenue"] / 1e6, marker="o", ms=3, lw=1.5)
ax.set_title("Monthly Revenue Trend (Dec 2009 – Dec 2011)")
ax.set_xlabel("Month"); ax.set_ylabel("Revenue (£ millions)")
ax.tick_params(axis="x", rotation=30)
fig.tight_layout(); fig.savefig(OUT / "monthly_revenue.png"); plt.close(fig)

peak = monthly.loc[monthly["Revenue"].idxmax()]
print(f"\n[Monthly trend] total revenue £{TOTAL_REVENUE:,.0f}; "
      f"peak month {peak['Month'].strftime('%Y-%m')} (£{peak['Revenue']:,.0f})")

# ============================================================ 4. RFM SEGMENTS
ref_date = df["InvoiceDate"].max() + pd.Timedelta(days=1)
rfm = (df.groupby("CustomerID")
         .agg(Recency=("InvoiceDate", lambda d: (ref_date - d.max()).days),
              Frequency=("InvoiceNo", "nunique"),
              Monetary=("Revenue", "sum"))
         .reset_index())

def qscore(series, reverse=False):
    """Quantile score 1–5 (5 = best). rank() avoids qcut duplicate-edge errors."""
    ranks = series.rank(method="first")
    labels = [5, 4, 3, 2, 1] if reverse else [1, 2, 3, 4, 5]
    return pd.qcut(ranks, 5, labels=labels).astype(int)

rfm["R"] = qscore(rfm["Recency"], reverse=True)
rfm["F"] = qscore(rfm["Frequency"])
rfm["M"] = qscore(rfm["Monetary"])
rfm["RFM"] = rfm["R"].astype(str) + rfm["F"].astype(str) + rfm["M"].astype(str)

def segment(row):
    r, f, m = row["R"], row["F"], row["M"]
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if f >= 4 and m >= 3:
        return "Loyal Customers"
    if r >= 4 and f <= 2:
        return "New Customers" if f == 1 and m <= 2 else "Potential Loyalists"
    if r == 3 and f <= 2:
        return "Promising"
    if r <= 2 and f >= 3:
        return "Can't Lose Them" if m >= 4 else "At Risk"
    if r == 2 and f <= 2:
        return "About to Sleep"
    if r == 1 and f <= 2:
        return "Hibernating"
    return "Need Attention"

rfm["Segment"] = rfm.apply(segment, axis=1)

seg = (rfm.groupby("Segment")
          .agg(Customers=("CustomerID", "nunique"), Revenue=("Monetary", "sum"))
          .assign(RevShare=lambda t: t["Revenue"] / t["Revenue"].sum() * 100)
          .sort_values("Revenue", ascending=False))
print("\n[RFM segments]")
print(seg.to_string(formatters={"Revenue": "£{:,.0f}".format, "RevShare": "{:.1f}%".format}))

order = seg.index.tolist()
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
sns.barplot(x=seg.loc[order, "Customers"], y=order, ax=axes[0], palette="Blues_r")
axes[0].set_title("Customers per Segment"); axes[0].set_xlabel("Customers")
sns.barplot(x=seg.loc[order, "RevShare"], y=order, ax=axes[1], palette="Greens_r")
axes[1].set_title("Revenue Share per Segment (%)"); axes[1].set_xlabel("Revenue share (%)")
fig.suptitle("RFM Customer Segmentation", y=1.02)
fig.tight_layout(); fig.savefig(OUT / "rfm_segments.png"); plt.close(fig)

# ================================== 5. REPURCHASE RATE & BASKET METRICS
orders = (df.groupby("InvoiceNo")
            .agg(Revenue=("Revenue", "sum"), Items=("Quantity", "sum"),
                 CustomerID=("CustomerID", "first")))
n_orders = len(orders)
n_customers = rfm.shape[0]
repeaters = (rfm["Frequency"] > 1).sum()
repurchase_rate = repeaters / n_customers * 100
aov = orders["Revenue"].mean()
items_per_order = orders["Items"].mean()
median_aov = orders["Revenue"].median()

print(f"\n[Repurchase & basket]")
print(f"  customers with 2+ orders: {repeaters:,} / {n_customers:,} "
      f"→ repurchase rate {repurchase_rate:.1f}%")
print(f"  avg order value (AOV): £{aov:,.2f}  (median £{median_aov:,.2f})")
print(f"  avg items per order: {items_per_order:,.1f}")

fig, ax = plt.subplots(figsize=(7, 4))
freq_counts = rfm["Frequency"].clip(upper=6).value_counts().sort_index()
labels = [str(i) if i < 6 else "6+" for i in freq_counts.index]
ax.bar(labels, freq_counts.values, color="steelblue")
ax.set_title("Distribution of Orders per Customer")
ax.set_xlabel("Orders per customer"); ax.set_ylabel("Customers")
fig.tight_layout(); fig.savefig(OUT / "orders_per_customer.png"); plt.close(fig)

# ================================================= 6. PRODUCT CATEGORIES
# The dataset has no category column → derive one from Description keywords.
CATEGORY_KEYWORDS = {
    "Home Decor": ["cushion", "frame", "mirror", "clock", "vase", "candle holder",
                   "wall art", "ornament", "decoration", "wreath", "garland",
                   "wicker", "bunting", "chest"],
    "Kitchen & Dining": ["mug", "cup", "plate", "teapot", "kettle", "cutlery",
                         "bowl", "glass", "jug", "tray", "placemat", "apron",
                         "oven", "baking", "kitchen", "cake stand", "cakestand"],
    "Garden & Outdoor": ["garden", "plant", "planter", "watering", "bird",
                         "lantern", "outdoor", "parasol"],
    "Toys & Games": ["toy", "doll", "teddy", "puzzle", "game", "balloon",
                     "kite", "play", "block word"],
    "Stationery & Craft": ["notebook", "pen", "pencil", "card", "paper",
                           "sticker", "stamp", "craft", "paint", "drawing"],
    "Lighting": ["lamp", "light", "fairy lights", "chandelier"],
    "Textiles & Comfort": ["towel", "blanket", "quilt", "pillow", "rug",
                           "curtain", "tea towel", "hot water bottle"],
    "Bags & Storage": ["bag", "basket", "box", "storage", "trunk", "tote",
                       "shopper"],
    "Party & Seasonal": ["christmas", "party", "birthday", "halloween",
                         "easter", "valentine"],
    "Candles & Fragrance": ["candle", "scent", "fragrance", "diffuser",
                            "incense"],
    "Signs, Doormats & Wall": ["sign", "chalkboard", "blackboard", "doormat",
                               "memoboard"],
}

def categorize(desc):
    d = str(desc).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in d for kw in kws):
            return cat
    return "Other"

df["Category"] = df["Description"].apply(categorize)

cat = (df.groupby("Category")
         .agg(Revenue=("Revenue", "sum"), Units=("Quantity", "sum"),
              Orders=("InvoiceNo", "nunique"))
         .assign(RevShare=lambda t: t["Revenue"] / t["Revenue"].sum() * 100)
         .sort_values("Revenue", ascending=False))
print("\n[Categories by revenue]")
print(cat.to_string(formatters={"Revenue": "£{:,.0f}".format, "RevShare": "{:.1f}%".format}))

top_cat = cat[cat.index != "Other"].head(8)
coverage = (1 - cat.loc["Other", "Revenue"] / cat["Revenue"].sum()) * 100 \
    if "Other" in cat.index else 100.0
print(f"  keyword-mapping revenue coverage: {coverage:.1f}%")
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(x=top_cat["Revenue"] / 1e6, y=top_cat.index, ax=ax, palette="viridis")
ax.set_title("Revenue by Product Category (Top 8)")
ax.set_xlabel("Revenue (£ millions)")
for i, v in enumerate(top_cat["Revenue"] / 1e6):
    ax.text(v + 0.02, i, f"£{v:.2f}M", va="center", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "category_revenue.png"); plt.close(fig)

# ==================================================== 7. GEOGRAPHIC ANALYSIS
geo = (df.groupby("Country")
         .agg(Revenue=("Revenue", "sum"), Orders=("InvoiceNo", "nunique"),
              Customers=("CustomerID", "nunique"))
         .assign(RevShare=lambda t: t["Revenue"] / t["Revenue"].sum() * 100)
         .sort_values("Revenue", ascending=False))
print("\n[Top 10 countries by revenue]")
print(geo.head(10).to_string(formatters={"Revenue": "£{:,.0f}".format, "RevShare": "{:.1f}%".format}))

top_geo = geo.head(10)
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(x=top_geo["RevShare"], y=top_geo.index, ax=ax, palette="magma")
ax.set_title("Revenue Share by Country (Top 10)")
ax.set_xlabel("Revenue share (%)")
for i, v in enumerate(top_geo["RevShare"]):
    ax.text(v + 0.3, i, f"{v:.1f}%", va="center", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "country_revenue.png"); plt.close(fig)

# ================================================================= HEADLINES
uk_share = geo.loc["United Kingdom", "RevShare"] if "United Kingdom" in geo.index else np.nan
top3_seg_rev = seg.head(3)["RevShare"].sum()
print("\n==================== KEY FINDINGS ====================")
print(f"• Clean dataset: {len(df):,} transactions, {n_customers:,} customers, "
      f"{n_orders:,} orders across {df['Country'].nunique()} countries "
      f"({df['InvoiceDate'].min().date()} → {df['InvoiceDate'].max().date()})")
print(f"• Total revenue: £{TOTAL_REVENUE:,.0f}; peak month {peak['Month'].strftime('%b %Y')} "
      f"(£{peak['Revenue']:,.0f})")
print(f"• Repurchase rate: {repurchase_rate:.1f}% of customers placed 2+ orders")
print(f"• Average order value: £{aov:,.2f} (median £{median_aov:,.2f}); "
      f"avg {items_per_order:,.1f} items per order")
print(f"• Top 3 RFM segments ({', '.join(seg.head(3).index)}) drive "
      f"{top3_seg_rev:.1f}% of revenue")
print(f"• Largest RFM segment: {seg['Customers'].idxmax()} "
      f"({seg['Customers'].max():,} customers)")
named_cat = cat[cat.index != "Other"]
print(f"• Top product category: {named_cat.index[0]} (£{named_cat.iloc[0]['Revenue']:,.0f}, "
      f"{named_cat.iloc[0]['RevShare']:.1f}% of revenue; "
      f"keyword mapping covers {coverage:.0f}% of revenue)")
print(f"• Geographic concentration: United Kingdom = {uk_share:.1f}% of revenue")
print("======================================================")
print(f"Figures saved to {OUT}/")
