## システム構成図

![システム構成図](./docs/infra.png)

## 開発環境構築手順

### 前提

- aws cliを使ってAWS環境にアクセス可能なこと
- serverless frameworkがインストールされていること
- python3.9がインストールされていること
- poetryがインストールされていること
- dockerがインストールされていること
- 本gitリポジトリをcloneできていること

### 手順

1. serverless frameworkを動かすためのパッケージをインストール

    ```sh
    npm install
    ```

2. pythonのライブラリインストール

    ```sh
    poetry install
    ```

3. pythonの仮想環境を作成

    ```sh
    poetry shell
    ```

4. プログラムをローカル実行

    ```sh
    sls invoke local -f {関数名}
    ```

    関数に引き渡すevent情報がある場合、以下のコマンドで実行
    
    ```sh
    sls invoke local -f {関数名} -p {ファイルパス}
    ```

#### event情報のサンプル

APIのLambda関数は、以下のフォーマットのファイルをevent情報として引き渡す。

```json
{"body": "{\"user_id\": \"hello\", \"rate\": 1500}"}
```


## デプロイ手順

### 前提

開発環境ができていること。

### 手順

1. 特定のLambda関数のみデプロイする場合

    ```sh
    sls deploy function -f {関数名} -s dev
    ```

2. インフラも含めてすべてデプロイする場合

    ```sh
    sls deploy -s dev
    ```

3. デプロイしたLambdaを実行

    ```sh
    sls invoke -f {関数名} -s dev
    ```

4. デプロイしたAPIを実行(サンプル)

    ```sh
    curl -i -X GET -H "x-api-key: ${api_key}" "https://{ドメイン}/dev/v1/{エンドポイント}"
    ```

    ドメイン、およびapi_keyはAWSのAPI Gatewayから確認

5. デプロイしたプログラムの動作確認用テスト

    ```sh
    pytest -sv tests
    ```
