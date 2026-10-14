import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# ---------------- STAGE 1: DATA CLEANING ----------------
# load the data and check size
df = pd.read_csv("comprehensive_mutual_funds_data.csv")
print(df.shape)
print(df.head())
df.info()

# columns with "-" were read as text, convert them to numbers
for col in ["sortino", "alpha", "sd", "beta", "sharpe"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# count missing values in each column
missing = df.isnull().sum()
print(missing[missing > 0])

# funds with missing 3 year return are only 2-3 years old, so they are not filled
print(df[df["returns_3yr"].isnull()]["fund_age_yr"].value_counts())

# remove columns not needed
df = df.drop(columns=["sortino", "alpha", "beta"])

# find wrong data: same 1/3/5 year returns for 3+ funds of different sub categories
return_cols = ["returns_1yr", "returns_3yr", "returns_5yr"]
groups = df.groupby(return_cols).agg(funds=("scheme_name", "count"),
                                      sub_categories=("sub_category", "nunique"))
bad = groups[(groups["funds"] >= 3) & (groups["sub_categories"] >= 2)]
print(bad)

# mark the wrong rows and remove their return values
bad = bad.reset_index()[return_cols]
bad["wrong_data"] = True
df = df.merge(bad, on=return_cols, how="left")
df["wrong_data"] = df["wrong_data"].fillna(False).astype(bool)
print("Funds with wrong return data:", df["wrong_data"].sum())
df.loc[df["wrong_data"], return_cols] = None

# add fund id, and use category as fund type
df["fund_id"] = df.index + 1
df["fund_type"] = df["category"]

# ---------------- STAGE 2: DATA UNDERSTANDING ----------------
# mean, median, mode, min, max, std
main_cols = ["returns_1yr", "returns_3yr", "returns_5yr", "expense_ratio",
             "fund_size_cr", "fund_age_yr", "risk_level"]
stats = df[main_cols].describe().T[["mean", "50%", "min", "max", "std"]]
stats = stats.rename(columns={"50%": "median"})
stats["mode"] = df[main_cols].mode().iloc[0]
print(stats.round(2))
stats.round(2).to_excel("statistics_table.xlsx")

# distribution plots (each one is a separate figure and is also saved as a picture)
ax = df[["returns_3yr"]].hist(bins=30, figsize=(6, 4))[0][0]
ax.set_title("3 year return (%)")
ax.figure.savefig("plot_returns_3yr.png")

ax = df["risk_level"].value_counts().sort_index().to_frame().plot.bar(
    subplots=True, legend=False, figsize=(6, 4), title="Number of funds by risk level")[0]
ax.figure.savefig("plot_risk_level.png")

ax = df["fund_age_yr"].value_counts().sort_index().to_frame().plot.bar(
    subplots=True, legend=False, figsize=(6, 4), title="Number of funds by age (years)")[0]
ax.figure.savefig("plot_fund_age.png")

ax = df[["expense_ratio"]].hist(bins=30, figsize=(6, 4))[0][0]
ax.set_title("Expense ratio (%)")
ax.figure.savefig("plot_expense_ratio.png")

# skewness: positive means long tail on the right
print(df[["returns_1yr", "returns_3yr", "expense_ratio", "fund_size_cr", "fund_age_yr"]].skew().round(2))

# average of each category
print(df.groupby("category")[["returns_1yr", "returns_3yr", "expense_ratio", "sd", "risk_level"]].mean().round(2))

# outliers: highest 1 year returns
print(df.sort_values("returns_1yr", ascending=False)[["scheme_name", "category", "returns_1yr", "returns_3yr", "returns_5yr"]].head(5))
ax = df.boxplot(column="returns_1yr", by="category", rot=20, figsize=(8, 5))
ax.figure.savefig("plot_boxplot_1yr.png")

# ---------------- STAGE 3: NORMALISATION ----------------
# only funds with a 3 year return can be ranked
ranked = df[df["returns_3yr"].notnull()].copy()
print("Funds that can be ranked:", len(ranked))

# MinMaxScaler: change values to 0-1 scale
scaler = MinMaxScaler()
ranked[["ret3_scaled", "exp_scaled", "risk_scaled"]] = scaler.fit_transform(
    ranked[["returns_3yr", "expense_ratio", "risk_level"]])
print(ranked[["ret3_scaled", "exp_scaled", "risk_scaled"]].describe().loc[["min", "max", "mean"]].round(2))

# ---------------- STAGE 4: SCORING AND RANKING ----------------
# age score: best at 7 years, goes down on both sides
ranked["age_score"] = 1 - (ranked["fund_age_yr"] - 7).abs() / 6
ranked["age_score"] = ranked["age_score"].clip(lower=0)

# positive 1 year return = 1, otherwise 0
ranked["positive_1yr"] = (ranked["returns_1yr"] > 0).astype(int)

# score: return is good when high, expense and risk are good when low (so 1 - value)
ranked["score"] = 100 * (0.40 * ranked["ret3_scaled"]
                         + 0.15 * (1 - ranked["exp_scaled"])
                         + 0.10 * ranked["age_score"]
                         + 0.10 * ranked["positive_1yr"]
                         + 0.25 * (1 - ranked["risk_scaled"]))
ranked["score"] = ranked["score"].round(2)

# rank from highest score
ranked = ranked.sort_values("score", ascending=False)
ranked["rank"] = range(1, len(ranked) + 1)
print(ranked[["rank", "scheme_name", "category", "risk_level", "returns_3yr", "expense_ratio", "fund_age_yr", "score"]].head(10))

# which part is closest to the final score
parts = pd.DataFrame({
    "return": ranked["ret3_scaled"],
    "low expense": 1 - ranked["exp_scaled"],
    "age": ranked["age_score"],
    "positive 1yr": ranked["positive_1yr"],
    "low risk": 1 - ranked["risk_scaled"]})
print(parts.corrwith(ranked["score"]).round(2))

# try other weights (return, expense, age, positive 1yr, risk) and compare Top 30
other_weights = {
    "45/15/10/10/20": [0.45, 0.15, 0.10, 0.10, 0.20],
    "return heavy 55/10/5/10/20": [0.55, 0.10, 0.05, 0.10, 0.20],
    "safety heavy 25/15/10/10/40": [0.25, 0.15, 0.10, 0.10, 0.40],
    "equal weights": [0.20, 0.20, 0.20, 0.20, 0.20],
    "no risk (55/20/10/15/0)": [0.55, 0.20, 0.10, 0.15, 0.00]}

my_top30 = ranked.head(30)
for name, w in other_weights.items():
    new_score = 100 * (w[0] * ranked["ret3_scaled"] + w[1] * (1 - ranked["exp_scaled"])
                       + w[2] * ranked["age_score"] + w[3] * ranked["positive_1yr"]
                       + w[4] * (1 - ranked["risk_scaled"]))
    new_top30 = ranked.loc[new_score.nlargest(30).index]
    same = len(set(new_top30.index) & set(my_top30.index))
    print(name, "| same funds as my Top 30:", same,
          "| equity funds:", (new_top30["category"] == "Equity").sum(),
          "| average risk:", round(new_top30["risk_level"].mean(), 2),
          "| average 3yr return:", round(new_top30["returns_3yr"].mean(), 1))

# ---------------- STAGE 5: TOP 30 (EXCEL) ----------------
# take first 30 funds and save to Excel
top30 = ranked.head(30)
top30_table = top30[["rank", "scheme_name", "amc_name", "category", "sub_category", "fund_manager",
                     "risk_level", "rating", "returns_1yr", "returns_3yr", "returns_5yr",
                     "expense_ratio", "fund_age_yr", "fund_size_cr", "min_sip", "min_lumpsum", "score"]]
top30_table.to_excel("Top_30_Mutual_Funds.xlsx", sheet_name="Top 30", index=False)

# common points in Top 30
print(top30["category"].value_counts())
print(top30["risk_level"].value_counts().sort_index())
print(top30["sub_category"].value_counts().head(5))
print(top30["amc_name"].value_counts().head(5))
print(top30[["returns_3yr", "expense_ratio", "fund_age_yr"]].mean().round(2))

# ---------------- STAGE 7: INSIGHTS ----------------
# 1. AUM by fund type
aum = df.groupby("fund_type")["fund_size_cr"].sum().sort_values(ascending=False)
print(aum.round(0))
print("share %:", (aum / aum.sum() * 100).round(1).to_dict())
print("lead of first over second:", round(aum.iloc[0] - aum.iloc[1]))

# 2. fund manager with highest AUM
print(df.groupby("fund_manager")["fund_size_cr"].sum().sort_values(ascending=False).head(5).round(0))

# 3. lowest expense ratio
print(df.groupby("category")["expense_ratio"].mean().round(2).sort_values())
print(df.groupby("sub_category")["expense_ratio"].mean().round(3).sort_values().head(5))

# 4. best 1 year return
print(df.sort_values("returns_1yr", ascending=False)[["scheme_name", "category", "returns_1yr", "returns_5yr"]].head(3))

# 5. SIP and lump sum
print("SIP average:", round(df["min_sip"].mean(), 1), "| median:", df["min_sip"].median(),
      "| average without zeros:", round(df[df["min_sip"] > 0]["min_sip"].mean(), 1))
print("Lumpsum average:", round(df["min_lumpsum"].mean(), 1), "| median:", df["min_lumpsum"].median())

# 6. return vs risk by category
print(df.groupby("category").agg(avg_3yr_return=("returns_3yr", "mean"),
                                 avg_risk_sd=("sd", "mean"),
                                 avg_risk_level=("risk_level", "mean")).round(2))

# ---------------- SAVE CLEAN DATA FOR POWER BI ----------------
df["score"] = ranked["score"]
df["rank"] = ranked["rank"]
df.to_csv("mutual_funds_clean_for_powerbi.csv", index=False)
print("saved", df.shape)
