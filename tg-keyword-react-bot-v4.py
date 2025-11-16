#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram关键词监控机器人
监控指定频道的关键词，并在源群组中自动发送贴纸回复或向用户私信
每个用户只互动一次，通过 user_id 记录
"""

import re
import os
import json
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import InputStickerSetShortName, PeerUser
from telethon.extensions import markdown

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ 配置区 ============
API_ID = 'YOUR_API_ID'  # 从 https://my.telegram.org 获取
API_HASH = 'YOUR_API_HASH'  # 从 https://my.telegram.org 获取
PHONE = 'YOUR_PHONE_NUMBER'  # 你的手机号，格式：+8613800138000

# 监控的频道ID（可以是用户名或数字ID）
MONITOR_CHANNEL = 'YOUR_MONITOR_CHANNEL'  # 例如：'channel_username' 或 -1001234567890

# KEYWORD_ACTIONS 统一结构：
# 每个字段都是“可选”的
# action 必须是 reply / dm
KEYWORD_ACTIONS = {
    'a9c30dc64998': {
        'action': 'dm',
        'text': """这是一条公益信息, 只会向您发送一次.
This is a public service message and will only be sent to you once.
本信息是为了告知您, 您在(公开和私有)群组中的发言可以被检索, 并使得您成为广告信息的对象.
This message is to inform you that your messages in groups (including pubic and private ones) could be searched and you may become the target of spam.
为了对抗广告信息, 电报用户和群组都应该避免使用username.
To against spam, Telegram users and groups should avoid using usernames.
这是一个简单的演示视频 https://youtu.be/2bvV030PgUA
"""
    },
    '三色图': {
        'action': 'reply',
        'sticker_pack': 'fuckgfwnewbie',
        'sticker_index': 0
    },
    'naive': {
        'action': 'dm',
        'sticker_pack': 'fuckgfwnewbie',
        'sticker_index': 1
    }
}

INTERACTED_FILE = 'interacted_users.json'
# ================================


class KeywordMonitorBot:
    def __init__(self):
        self.client = TelegramClient('session_' + PHONE, API_ID, API_HASH)
        self.sticker_cache = {}
        self.interacted_users = self.load_interacted_users()

    # ---------------- 已互动用户持久化 ----------------
    def load_interacted_users(self):
        if os.path.exists(INTERACTED_FILE):
            try:
                with open(INTERACTED_FILE, 'r', encoding='utf-8') as f:
                    return {int(k): True for k in json.load(f).keys()}
            except Exception as e:
                logger.warning(f"加载已互动用户文件失败: {e}")
        return {}

    def save_interacted_users(self):
        try:
            with open(INTERACTED_FILE, 'w', encoding='utf-8') as f:
                json.dump({str(k): True for k in self.interacted_users.keys()},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存已互动用户文件失败: {e}")

    # ---------------- 获取贴纸 ----------------
    async def get_sticker(self, pack_name, index):
        """安全获取指定贴纸包的某个贴纸（index=0 也正确处理）"""
        cache_key = (pack_name, index)

        if cache_key in self.sticker_cache:
            return self.sticker_cache[cache_key]

        if pack_name is None or index is None:
            return None

        try:
            from telethon import functions
            sticker_set = await self.client(
                functions.messages.GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=pack_name),
                    hash=0
                )
            )

            docs = sticker_set.documents or []
            if index < 0 or index >= len(docs):
                logger.error(f"贴纸包 {pack_name} 不存在 index={index} 的贴纸")
                return None

            self.sticker_cache[cache_key] = docs[index]
            logger.info(f"预加载贴纸：{pack_name}[{index}]")
            return docs[index]

        except Exception as e:
            logger.error(f"获取贴纸 {pack_name}[{index}] 失败: {e}")
            return None

    # ---------------- 解析监控频道的通知 ----------------
    def parse_notification_message(self, text):
        result = {
            'source_channel': None,
            'source_message_id': None,
            'keyword': None,
            'sender_username': None,
            'sender_id': None
        }

        lines = text.split('\n')
        if not lines:
            return result

        first = lines[0]

        # 1. 私有频道 t.me/c
        m = re.search(r'https://t\.me/c/(\d+)/(\d+)', first)
        if m:
            cid = int('-100' + m.group(1))
            mid = int(m.group(2))
            result['source_channel'] = cid
            result['source_message_id'] = mid
        else:
            # 2. 公共频道 t.me/xxx
            m = re.search(r'https://t\.me/([^/\s]+)/(\d+)', first)
            if m:
                result['source_channel'] = m.group(1)
                result['source_message_id'] = int(m.group(2))

        # 3. 关键词
        m = re.search(r'"([^"]+)"', first)
        if m:
            result['keyword'] = m.group(1)

        # 4. 发送者
        m = re.search(r'FROM\s+([^(]+)\((@?[\w_]+)\)', first)
        if m:
            sid = m.group(2)
            if sid.startswith('@'):
                result['sender_username'] = sid[1:]
            else:
                try:
                    result['sender_id'] = int(sid)
                except:
                    pass

        return result

    # ---------------- 匹配关键词 ----------------
    def check_keywords(self, text):
        if not text:
            return []
        lower = text.lower()
        return [k for k in KEYWORD_ACTIONS if k.lower() in lower]

    # ---------------- 处理匹配动作 ----------------
    async def handle_keyword_match(self, keyword, info):
        cfg = KEYWORD_ACTIONS[keyword]

        action = cfg.get('action')
        text = cfg.get('text')
        pack = cfg.get('sticker_pack')
        index = cfg.get('sticker_index')

        sender_username = info.get('sender_username')
        source_channel = info.get('source_channel')
        source_message_id = info.get('source_message_id')
            
        # 1. 尝试取贴纸
        sticker = None
        if pack is not None and index is not None:
            sticker = await self.get_sticker(pack, index)

        # 2. 执行动作
        # 群回复
        if action == 'reply':
            if source_channel and source_message_id:
                if sticker:
                    await self.client.send_file(source_channel, sticker, reply_to=source_message_id)
                if text:
                    await self.client.send_message(source_channel, text, reply_to=source_message_id)
            return True

        # 私信
        if action == 'dm':
            entity = None
            final_user_id = None

            # 2.1 公共群且有 source_message_id → 通过消息拿 from_id
            if source_channel and source_message_id:
                try:
                    msg = await self.client.get_messages(source_channel, ids=source_message_id)
                    if msg and msg.from_id:
                        entity = PeerUser(msg.from_id.user_id)
                        logger.info(f"通过群消息获取到用户 ID: {msg.from_id.user_id}")
                        final_user_id = msg.from_id.user_id
                except Exception as e:
                    logger.warning(f"通过群消息获取用户实体失败: {e}")

            # 2.2 如果 entity 仍为空且有 username → 直接用 username
            if entity is None and sender_username:
                try:
                    entity = await self.client.get_input_entity(sender_username)
                    logger.info(f"通过 username 获取到用户实体: {sender_username}")
                    final_user_id = entity.user_id
                except Exception as e:
                    logger.warning(f"通过 username 获取用户实体失败: {e}")
                    entity = None

            # 2.3 如果最终仍没有 entity，无法发送
            if entity is None:
                logger.warning("无法获取用户实体，无法私信")
                return False

            # 3. 检查是否已互动
            if final_user_id in self.interacted_users:
                logger.info(f"用户 {final_user_id} 已互动过，跳过")
                return False

            # 发送贴纸
            if sticker:
                try:
                    await self.client.send_file(entity, sticker)
                except Exception as e:
                    logger.error(f"发送贴纸私信失败: {e}")

            # 发送文本
            if text:
                try:
                    await self.client.send_message(entity, text)
                except Exception as e:
                    logger.error(f"发送文本私信失败: {e}")

            # 记录已互动用户
            self.interacted_users[final_user_id] = True
            self.save_interacted_users()

            return True

        return False

    # ---------------- 启动机器人 ----------------
    async def start(self):
        await self.client.start(phone=PHONE)
        logger.info("机器人已启动")

        # 预加载贴纸
        for kw, cfg in KEYWORD_ACTIONS.items():
            if cfg.get('sticker_pack') is not None and cfg.get('sticker_index') is not None:
                await self.get_sticker(cfg['sticker_pack'], cfg['sticker_index'])

        @self.client.on(events.NewMessage(chats=MONITOR_CHANNEL))
        async def handler(event):
            msg = markdown.unparse(event.message.message, event.message.entities)
            matches = self.check_keywords(msg)

            if not matches:
                return

            info = self.parse_notification_message(msg)
            for kw in matches:
                await self.handle_keyword_match(kw, info)

        await self.client.run_until_disconnected()


async def main():
    bot = KeywordMonitorBot()
    await bot.start()


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
