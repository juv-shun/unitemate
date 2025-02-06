import json
import logging

import os
import json
import uuid
import boto3

# �e�������s�����W���[���̃C���|�[�g
from match_queue import inqueue, dequeue
from src.match_make import handle as match_make_handler
from src.match_report import handle as match_report_handler
from src.match_judge import handle as match_judge_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)



# boto3�N���C�A���g�̏�����
sqs = boto3.client('sqs')
# FIFO�L���[��URL�B���ϐ��ŊǗ�
QUEUE_URL = os.environ["AGGREGATION_QUEUE"]

def db_process_queue_handler(event, context):
    """
    SQS�̃��b�Z�[�W���󂯎��A���b�Z�[�W����"action"�ɉ������������Ăяo�������v���Z�X�p�̃n���h���[�B
    
    ���b�Z�[�W��:
    {
        "action": "match_make",    # enqueue, dequeue, queue_info, match_make,
                                   # notify_users, match_report, process_report,
                                   # match_judge, process_aggregation, user_upsert,
                                   # user_delete, user_info, get_ranking �Ȃ�
        "payload": { ... }         # �e�����ɕK�v�ȃp�����[�^
    }
    """
    records = event.get("Records", [])
    for record in records:
        try:
            message_body = record["body"]
            message = json.loads(message_body)
        except Exception as e:
            logger.error(f"���b�Z�[�W�̃p�[�X�G���[: {e}")
            continue

        action = message.get("action")
        payload = message.get("payload", {})
        logger.info(f"��M�A�N�V����: {action} / payload: {payload}")

        try:
            if action == "enqueue":
                inqueue(payload, context)
            elif action == "dequeue":
                dequeue(payload, context)
            elif action == "match_make":
                match_make_handler(payload, context)
            elif action == "match_report":
                match_report_handler(payload, context)
            elif action == "match_judge":
                match_judge_handler(payload, context)
            else:
                logger.error(f"�s���ȃA�N�V����: {action}")
        except Exception as ex:
            logger.error(f"�A�N�V���� {action} �̏������ɃG���[����: {ex}")

    return {"statusCode": 200, "body": "���ׂẴ��b�Z�[�W�𐳏�ɏ������܂����B"}



def send_sqs_message(action: str, payload: dict, group_id: str = "ProcessQueue", delay: int = 0):
    """
    SQS FIFO�L���[�Ƀ��b�Z�[�W�𑗐M���鋤�ʊ֐��B
    
    :param action: "inqueue", "dequeue", "match_make", "match_report", "process_result", "update_ranking" ���̑��얼
    :param payload: �e�����ɕK�v�ȃp�����[�^���i�[��������
    :param group_id: FIFO�L���[��MessageGroupId�i�S���b�Z�[�W��1�O���[�v�ɂ܂Ƃ߂�ꍇ�͌Œ�l�j
    :return: SQS�̑��M���X�|���X
    """
    message_body = json.dumps({
        "action": action,
        "payload": payload
    })
    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=message_body,
        MessageGroupId=group_id,
        DelaySeconds=delay,
        MessageDeduplicationId=str(uuid.uuid4()),
    )
    print(f"Enqueued {action} with MessageId: {response['MessageId']}")
    return response

def send_inqueue_message(event, _):
    """
    �C���L���[�v���̃��b�Z�[�W�𑗐M����B
    """
    return send_sqs_message("inqueue", event)

def send_dequeue_message(event, _):
    """
    �f�L���[�v���̃��b�Z�[�W�𑗐M����B
    """
    return send_sqs_message("dequeue", event)

def send_matchmake_message(event, _):
    """
    �}�b�`���C�N�v���̃��b�Z�[�W�𑗐M����B
    """
    return send_sqs_message("match_make", event)

def send_match_report_message(event, _):
    """
    �������ʕ񍐗v���̃��b�Z�[�W�𑗐M����B
    """
    return send_sqs_message("match_report", event)

def send_process_result_message(event, _, delay=0):
    """
    �������ʏ����v���̃��b�Z�[�W�𑗐M����B
    """
    return send_sqs_message("process_result", event, delay=delay)