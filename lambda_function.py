import boto3
import requests
from datetime import datetime, timedelta, timezone
import os
import json
import re

# === 設定 ===
LINE_TOKEN = os.environ['LINE_TOKEN']
LINE_USER_ID = os.environ['LINE_USER_ID']
USD_TO_JPY = 157.77
JST = timezone(timedelta(hours=9))
SEPARATOR = "━━━━━━━━━━━━━━━"

def get_aws_cost(start: str, end: str) -> tuple[float, list[tuple[str, float]]]:
    """Cost ExplorerでAWS料金を取得"""

    ce = boto3.client('ce', region_name='us-east-1')

    response = ce.get_cost_and_usage(
        TimePeriod={'Start': start, 'End': end},
        Granularity='MONTHLY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )

    results = response['ResultsByTime'][0]
    total = 0.0
    costs = []

    for group in results['Groups']:
        service = group['Keys'][0]
        amount = float(group['Metrics']['UnblendedCost']['Amount'])
        if amount > 0:
            costs.append((service, amount))
            total += amount

    costs.sort(key=lambda x: x[1], reverse=True)
    return total, costs

def send_line_message(message: str) -> None:
    """LINEにプッシュ通知"""
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Authorization': f'Bearer {LINE_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'to': LINE_USER_ID,
        'messages': [{'type': 'text', 'text': message}]
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"LINE送信結果: {response.status_code}")

def periodic_notification() -> str:
    """定期通知用(実行時の当月コスト)"""
    # 当月の開始・終了日
    today = datetime.now(JST)
    start = today.replace(day=1).strftime('%Y-%m-%d')
    end = (today + timedelta(days=1)).strftime('%Y-%m-%d')

    total, costs = get_aws_cost(start, end)
    message = format_line_message(total, costs, label="今月")
    return message

def format_line_message(total: float, costs: list[tuple[str, float]], label: str = "今月") -> str:
    """LINEメッセージ用に成形"""
    total_jpy = int(total * USD_TO_JPY)

    lines = [
        f"【AWS料金通知 - {label}】",
        SEPARATOR,
        f"合計: ${total:.2f} (¥{total_jpy:,})",
        SEPARATOR,
    ]
    for service, amount in costs:
        jpy = int(amount * USD_TO_JPY)
        lines.append(f"{service}: ${amount:.2f} (¥{jpy:,})")
    lines.append(SEPARATOR)
    lines.append(f"{datetime.now(JST).strftime('%Y/%m/%d')} 時点")

    message = "\n".join(lines)
    print(message)
    return message

def reply_line_message(reply_token: str, message: str) -> None:
    """replyTokenを使ってメッセージ送信"""
    url = 'https://api.line.me/v2/bot/message/reply'

    headers = {
        'Authorization': f'Bearer {LINE_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': message}]
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"LINE送信結果: {response.status_code}")

def parse_message(user_message: str) -> tuple[str, str, str] | None:
    if "コスト" not in user_message:
        return None  # ヘルプ扱い                                                                             

    today = datetime.now(JST)

    if "先月" in user_message:
        # 先月
        first = today.replace(day=1)
        end = first.strftime('%Y-%m-%d')
        start = (first - timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d')
        label = "先月"
    elif match := re.search(r'(\d{1,2})月', user_message):
        # 特定の月（「2月」「12月」など）
        month = int(match.group(1))
        start = today.replace(month=month, day=1).strftime('%Y-%m-%d')
        if month == 12:
            end = today.replace(year=today.year+1, month=1, day=1).strftime('%Y-%m-%d')
        else:
            end = today.replace(month=month+1, day=1).strftime('%Y-%m-%d')
        label = f"{month}月"
    else:
        # デフォルト: 今月
        start = today.replace(day=1).strftime('%Y-%m-%d')
        end = (today + timedelta(days=1)).strftime('%Y-%m-%d')
        label = "今月"

    return (start, end, label)

def lambda_handler(event, context):
    if 'events' in event:
        for ev in event['events']:
            if ev['type'] == 'message' and ev['message']['type'] == 'text':
                user_message = ev['message']['text']
                reply_token = ev['replyToken']
                result = parse_message(user_message)
                if result is None:
                    reply_line_message(reply_token, '「コスト」を含むメッセージを送ってください')
                else:
                    start, end, label = result
                    total, costs = get_aws_cost(start, end)
                    message = format_line_message(total, costs, label)
                    reply_line_message(reply_token, message)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'ok'})
        }
    else:
        send_line_message(periodic_notification())


