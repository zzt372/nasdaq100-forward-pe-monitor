# Nasdaq 100 Forward P/E Monitor

Trendonify の **Nasdaq 100 Forward PE Ratio** を監視する GitHub Actions リポジトリです。

## 本番構成

- メインワークフローは UTC の `3,13,23,33,43,53` 分、つまり約10分ごとに実行します。
- 独立した Watchdog は UTC の `8,28,48` 分に実行し、commit 済み状態が厳格な健全性検証に失敗した場合、または `fetched_at` が60分以上古い場合だけ復旧処理を行います。
- メインと Watchdog は同じ GitHub Actions concurrency group を `queue: max` で共有し、重複実行時はキャンセルではなく直列化します。
- 追跡対象の Trendonify 系列は、次の Nasdaq 100 Forward PE Ratio 専用ページに固定しています。
  `https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio`
- Trendonify は GitHub-hosted runner のIPを HTTP 403 / Cloudflare で拒否することがあるため、実値は DuckDuckGo Lite 経由で **上記の専用Trendonifyページそのものの公開検索インデックス結果** を読み取ります。DuckDuckGo はあくまで転送経路であり、他ドメインの値は採用しません。
- 本番1回の実行につき検索リクエストは1回だけです。同一runnerから検索を連打するとbot challengeの確率が上がるため、意図的に再検索を行いません。
- 正常値として採用するには、**Forward P/E・10年パーセンタイル・インデックス上の日付** の3項目が、同じTrendonify結果ブロック内に揃っている必要があります。別のTrendonifyページや別の検索結果から値を合成しません。
- 同一内容の重複結果ブロックは許可しますが、値が矛盾する重複結果はfail closedで拒否します。
- 取得、解析、source identity、鮮度、sanity checkのいずれかに失敗した場合、last-known-good の `latest.json` は上書きしません。
- 毎回の本番取得前に回帰テストを実行し、生成したpayloadもcommit前に再検証します。
- 値・日付・source等に実質的な変化があれば即commitします。値が変わらない場合でも約40分ごとにheartbeat commitを行い、10分ごとに不要なcommitを増やさず、consumer側が鮮度を確認できるようにします。
- GitHub Actions の `checkout` と `setup-python` は現在の v7 系を使用しています。
- APIキーやRepository Secretsは不要です。

## 検証・fail-closedルール

producer側では、少なくとも以下を拒否します。

- Trendonify結果ブロックの欠落・破損
- DuckDuckGoのbot / CAPTCHA challengeページ
- 他プロバイダを誤って一致結果として扱うケース
- 対象とは異なるTrendonify URL
- 同一ページについて矛盾する複数tupleが返るケース
- P/E が `1..100` の範囲外
- 10年パーセンタイルが `0..100` の範囲外
- data date が1日超未来、または7暦日超古い
- 前回の正常値より古い data date への巻き戻り
- 誤った指標や壊れた検索結果を強く疑う極端な同日・短時間ジャンプのみ拒否します。実際の大きな相場変動は許可します。
- `fetched_at` の形式不正、鮮度切れ、不自然な未来時刻
- schema / source / source URL / source kind / fetch method の不一致

## Trendonifyの表現を1つに固定する理由

Trendonifyでは、Forward P/E一覧、Nasdaq 100概要ページ、Forward P/E専用ページ・検索インデックスで、同じ時点でも数値がわずかに異なる場合があります。

これらを混ぜて比較すると、本当は正常でも「矛盾」と判定して誤った障害扱いやノイズ通知につながります。そのため、このリポジトリでは **1つの固定した系列 identity と、1つの結果ブロック内に揃った完全なtupleだけ** を追跡します。別のTrendonify表現を暗黙fallbackとして使うことはありません。

## `latest.json` を読む側の推奨検証

consumer側では以下を確認してください。

- `schema_version == 2`
- `ok == true`
- `forward_pe` が数値で `1..100`
- `percentile_10y` が数値で `0..100`
- `data_date` が妥当かつ十分新しく、前回正常値より巻き戻っていない
- `fetched_at` がtimezone付きで、不自然な未来ではなく、consumer側SLAに対して十分新しい
- `source == "Trendonify"`
- `source_url == "https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"`
- `source_kind == "dedicated-forward-pe-search-index"`
- `fetch_method == "duckduckgo-lite"`

ChatGPT側のconsumerでは `fetched_at` を約90分まで許容します。GitHubのscheduled workflowはbest-effortであり、一方で独立Watchdogはcommit済みデータが60分を超えて古くなった時点から復旧を開始するためです。

## 実施済みの障害系テスト

複数の新しい GitHub-hosted runner を使った統合テストで、次を確認しています。

1. 同一Trendonify tupleを複数runnerから繰り返し正常取得できること
2. stale状態を正しく判定できること
3. recovery取得後に再検証まで正常完了すること
4. 疑似的な取得失敗 / CAPTCHA失敗を発生させても、last-known-good の `latest.json` がバイト単位で保持されること

この設計では、**推測値・不完全値・別ページ混在値・別ソース値を公開するより、既知の正常値を保持して静かに失敗すること** を優先します。
