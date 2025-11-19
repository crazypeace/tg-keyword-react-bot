#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram关键词监控机器人
监控指定频道的关键词，并在源群组中自动发送贴纸回复或向用户私信
"""

import re
import logging
import time # 引入time模块用于时间戳
from telethon import TelegramClient, events
from telethon.tl.types import InputStickerSetShortName, DocumentAttributeSticker
from telethon.extensions import markdown
from telethon import functions 

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

# 要监控的关键词列表及对应动作
# 动作类型: 'reply' - 在源消息回复, 'dm' - 私信发送者
KEYWORD_ACTIONS = {
    '三色图': {'action': 'reply', 'sticker_pack': 'fuckgfwnewbie', 'sticker_index': 0},
    'naive': {'action': 'reply', 'sticker_pack': 'fuckgfwnewbie', 'sticker_index': 1},  # 第2个贴纸
    '✌': {'action': 'reply', 'sticker_pack': 'fuckgfwnewbie', 'sticker_index': 2},  # 第3个贴纸
    'cloudflare': {'action': 'reply', 'sticker_pack': 'fuckgfwnewbie', 'sticker_index': 3},  # 第4个贴纸
}

# 冷却时间（秒）：1 小时 = 3600 秒
COOLDOWN_SECONDS = 3600

# ================================


class KeywordMonitorBot:
    def __init__(self):
        self.client = TelegramClient('session_' + PHONE, API_ID, API_HASH)
        self.sticker_cache = {}  # 缓存贴纸: {(pack_name, index): file_id}
        # 新增：记录群组最后一次响应时间 {channel_id: timestamp}
        self.last_action_time = {} 
        
    async def get_sticker(self, pack_name, sticker_index):
        """获取指定贴纸包的贴纸"""
        cache_key = (pack_name, sticker_index)
        
        # 检查缓存
        if cache_key in self.sticker_cache:
            return self.sticker_cache[cache_key]
        
        try:

            sticker_set = await self.client(
                functions.messages.GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=pack_name),
                    hash=0
                )
            )
            
            if sticker_set.documents and len(sticker_set.documents) > sticker_index:
                sticker_file = sticker_set.documents[sticker_index]
                self.sticker_cache[cache_key] = sticker_file
                logger.info(f"成功获取贴纸包 {pack_name} 的第 {sticker_index + 1} 个贴纸")
                return sticker_file
            else:
                logger.error(f"贴纸包 {pack_name} 中没有足够的贴纸 (需要至少 {sticker_index + 1} 个)")
                return None
        except Exception as e:
            logger.error(f"获取贴纸失败: {e}")
            return None
    
    def parse_notification_message(self, message_text):
        """
        解析监控频道的通知消息
        返回: {
            'source_channel': 源频道ID或用户名,
            'source_message_id': 源消息ID,
            'keyword': 匹配的关键词,
            'group_info': 群组信息,
            'sender_username': 发送者用户名,
            'sender_id': 发送者ID
        }
        """
        result = {
            'source_channel': None,
            'source_message_id': None,
            'keyword': None,
            'group_info': None,
            'sender_username': None,
            'sender_id': None
        }
        
        # 解析第一行: #FOUND (源链接) "关键词" IN 群组 FROM 用户
        # 示例: #FOUND (https://t.me/c/1958152252/300436) "自建" IN Joey Huang Blog(1958152252) FROM jacky jay(5979280761)
        
        lines = message_text.split('\n')
        if not lines:
            return result
        
        first_line = lines[0]
        
        # 提取源链接
        # 私有频道: https://t.me/c/1958152252/300436
        private_pattern = r'https://t\.me/c/(\d+)/(\d+)'
        private_match = re.search(private_pattern, first_line)
        if private_match:
            result['source_channel'] = int('-100' + private_match.group(1))
            result['source_message_id'] = int(private_match.group(2))
        else:
            # 公开频道: https://t.me/LoonCommunity/161393
            public_pattern = r'https://t\.me/([^/\s]+)/(\d+)'
            public_match = re.search(public_pattern, first_line)
            if public_match:
                result['source_channel'] = public_match.group(1)
                result['source_message_id'] = int(public_match.group(2))
        
        # 提取关键词
        keyword_pattern = r'"([^"]+)"'
        keyword_match = re.search(keyword_pattern, first_line)
        if keyword_match:
            result['keyword'] = keyword_match.group(1)
        
        # 提取发送者信息
        # FROM 后面可能是: jacky jay(5979280761) 或 Yang Bo(@Zen_Neng_Bu_Bian_Tai)
        from_pattern = r'FROM\s+([^(]+)\((@?[\w_]+)\)'
        from_match = re.search(from_pattern, first_line)
        if from_match:
            sender_name = from_match.group(1).strip()
            sender_identifier = from_match.group(2)
            
            # 判断是ID还是用户名
            if sender_identifier.startswith('@'):
                result['sender_username'] = sender_identifier[1:]  # 去掉@
            else:
                try:
                    result['sender_id'] = int(sender_identifier)
                except ValueError:
                    logger.warning(f"无法解析发送者ID: {sender_identifier}")
        
        return result
    
    async def send_sticker_reply(self, channel_id, message_id, sticker_file):
        """在源消息处发送贴纸作为回复"""
        try:
            await self.client.send_file(
                channel_id,
                sticker_file,
#                reply_to=message_id   # 注释掉, 不回复, 改为直接发
            )
            logger.info(f"成功在 {channel_id} 的消息 {message_id} 发送贴纸")
            return True
        except Exception as e:
            logger.error(f"发送贴纸失败: {e}")
            return False
    
    async def send_sticker_dm(self, user_identifier, sticker_file):
        """向用户私信发送贴纸"""
        try:
            await self.client.send_file(
                user_identifier,
                sticker_file
            )
            logger.info(f"成功向用户 {user_identifier} 发送私信贴纸")
            return True
        except Exception as e:
            logger.error(f"发送私信贴纸失败: {e}")
            return False
    
    def check_keywords(self, text):
        """检查文本是否包含关键词，返回匹配的关键词列表"""
        if not text:
            return []
        
        text_lower = text.lower()
        matched = []
        
        for keyword in KEYWORD_ACTIONS.keys():
            if keyword.lower() in text_lower:
                matched.append(keyword)
        
        return matched
    
    async def handle_keyword_match(self, keyword, parsed_info):
        """处理关键词匹配"""
        action_config = KEYWORD_ACTIONS[keyword]
        action_type = action_config['action']
        source_channel = parsed_info['source_channel']

        # 检查冷却时间 仅对 action='reply' 有效
        if action_type == 'reply' and source_channel:
            now = time.time()
            last_time = self.last_action_time.get(source_channel)
            
            if last_time and (now - last_time < COOLDOWN_SECONDS):
                remaining = COOLDOWN_SECONDS - (now - last_time)
                logger.info(f"群组 {source_channel} 处于冷却期。剩余 {remaining:.0f} 秒，跳过响应。")
                return False
        
        sticker_pack = action_config['sticker_pack']
        sticker_index = action_config['sticker_index']
        
        # 获取贴纸
        sticker_file = await self.get_sticker(sticker_pack, sticker_index)
        if not sticker_file:
            logger.error(f"无法获取贴纸: {sticker_pack}[{sticker_index}]")
            return False
        
        if action_type == 'reply':
            # 在源消息回复
            if source_channel and parsed_info['source_message_id']:
                result = await self.send_sticker_reply(
                    source_channel,
                    parsed_info['source_message_id'],
                    sticker_file
                )
                # 如果回复成功，更新冷却时间戳
                if result and source_channel:
                    self.last_action_time[source_channel] = time.time()
                    logger.info(f"群组 {source_channel} 已成功响应并进入 {COOLDOWN_SECONDS} 秒冷却期。")
                return result
            else:
                logger.warning("无法提取源消息信息，无法回复")
                return False
                
        elif action_type == 'dm':
            # 私信发送者
            # 优先使用用户名，其次使用ID
            user_identifier = None
            if parsed_info['sender_username']:
                user_identifier = parsed_info['sender_username']
            elif parsed_info['sender_id']:
                user_identifier = parsed_info['sender_id']
            
            if user_identifier:
                return await self.send_sticker_dm(user_identifier, sticker_file)
            else:
                logger.warning("无法提取发送者信息，无法发送私信")
                return False
        
        return False
    
    async def start(self):
        """启动机器人"""
        await self.client.start(phone=PHONE)
        logger.info("机器人已启动")
        
        # 预加载所有贴纸
        for keyword, config in KEYWORD_ACTIONS.items():
            await self.get_sticker(config['sticker_pack'], config['sticker_index'])
        
        # 注册消息处理器
        @self.client.on(events.NewMessage(chats=MONITOR_CHANNEL))
        async def handler(event):
            message_text = markdown.unparse(event.message.message, event.message.entities)
            
            # 检查是否包含关键词
            matched_keywords = self.check_keywords(message_text)
            
            if matched_keywords:
                logger.info(f"检测到关键词: {matched_keywords}")
                logger.info(f"消息内容: {message_text[:200]}")
                
                # 解析消息
                parsed_info = self.parse_notification_message(message_text)
                logger.info(f"解析结果: {parsed_info}")
                
                # 处理每个匹配的关键词
                for keyword in matched_keywords:
                    await self.handle_keyword_match(keyword, parsed_info)
        
        logger.info(f"开始监控频道: {MONITOR_CHANNEL}")
        logger.info(f"监控关键词及动作:")
        for keyword, config in KEYWORD_ACTIONS.items():
            action_desc = "源消息回复" if config['action'] == 'reply' else "私信发送者"
            logger.info(f"  - '{keyword}' -> {action_desc} (贴纸包: {config['sticker_pack']}, 索引: {config['sticker_index']})")
        
        # 保持运行
        await self.client.run_until_disconnected()


async def main():
    bot = KeywordMonitorBot()
    await bot.start()


if __name__ == '__main__':
    import asyncio
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人已停止")