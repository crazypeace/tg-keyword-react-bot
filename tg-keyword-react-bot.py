#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram关键词监控机器人
监控指定频道的关键词，并在源群组中自动发送贴纸
"""

import re
import logging
from telethon import TelegramClient, events
from telethon.tl.types import InputStickerSetShortName, DocumentAttributeSticker
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

# 要监控的关键词列表
KEYWORDS = ['三色图']  # 可以添加多个关键词

# 贴纸包信息
STICKER_PACK = 'fuckgfwnewbie'  # 贴纸包短名称
STICKER_INDEX = 0  # 第1个贴纸（索引从0开始）

# ================================


class KeywordMonitorBot:
    def __init__(self):
        self.client = TelegramClient('session_' + PHONE, API_ID, API_HASH)
        self.sticker_file_id = None
        
    async def get_sticker(self):
        """获取指定贴纸包的贴纸"""
        try:
            sticker_set = await self.client(
                functions.messages.GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=STICKER_PACK),
                    hash=0
                )
            )
            
            if sticker_set.documents and len(sticker_set.documents) > STICKER_INDEX:
                self.sticker_file_id = sticker_set.documents[STICKER_INDEX]
                logger.info(f"成功获取贴纸包 {STICKER_PACK} 的第 {STICKER_INDEX + 1} 个贴纸")
                return True
            else:
                logger.error(f"贴纸包中没有足够的贴纸 (需要至少 {STICKER_INDEX + 1} 个)")
                return False
        except Exception as e:
            logger.error(f"获取贴纸失败: {e}")
            return False
    
    def extract_source_info(self, message_text):
        """从监控消息中提取源群组信息"""
        # 匹配格式: #FOUND (https://t.me/c/CHANNEL_ID/MESSAGE_ID) 或
        # #FOUND (https://t.me/USERNAME/MESSAGE_ID)
        
        # 私有频道格式: https://t.me/c/1958152252/300436
        private_pattern = r'https://t\.me/c/(\d+)/(\d+)'
        private_match = re.search(private_pattern, message_text)
        if private_match:
            channel_id = int('-100' + private_match.group(1))  # 转换为完整ID
            message_id = int(private_match.group(2))
            return channel_id, message_id
        
        # 公开频道格式: https://t.me/LoonCommunity/161393
        public_pattern = r'https://t\.me/([^/\s]+)/(\d+)'
        public_match = re.search(public_pattern, message_text)
        if public_match:
            channel_username = public_match.group(1)
            message_id = int(public_match.group(2))
            return channel_username, message_id
        
        return None, None
    
    async def send_sticker_to_source(self, channel_id, message_id):
        """在源消息处发送贴纸"""
        try:
            if not self.sticker_file_id:
                logger.warning("贴纸未加载，尝试重新获取")
                if not await self.get_sticker():
                    return False
            
            await self.client.send_file(
                channel_id,
                self.sticker_file_id
            )
            logger.info(f"成功在 {channel_id} 发送贴纸")
            return True
        except Exception as e:
            logger.error(f"发送贴纸失败: {e}")
            return False
    
    def contains_keyword(self, text):
        """检查文本是否包含关键词"""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in KEYWORDS)
    
    async def start(self):
        """启动机器人"""
        await self.client.start(phone=PHONE)
        logger.info("机器人已启动")
        
        # 获取贴纸
        await self.get_sticker()
        
        # 注册消息处理器
        @self.client.on(events.NewMessage(chats=MONITOR_CHANNEL))
        async def handler(event):
            message_text = markdown.unparse(event.message.message, event.message.entities)
            
            # 检查是否包含关键词
            if self.contains_keyword(message_text):
                logger.info(f"检测到关键词: {message_text[:100]}")
                
                # 提取源群组信息
                source_channel, source_message_id = self.extract_source_info(message_text)
                
                if source_channel and source_message_id:
                    logger.info(f"找到源消息: 频道={source_channel}, 消息ID={source_message_id}")
                    await self.send_sticker_to_source(source_channel, source_message_id)
                else:
                    logger.warning("无法提取源消息信息")
        
        logger.info(f"开始监控频道: {MONITOR_CHANNEL}")
        logger.info(f"监控关键词: {', '.join(KEYWORDS)}")
        
        # 保持运行
        await self.client.run_until_disconnected()


async def main():
    bot = KeywordMonitorBot()
    await bot.start()


if __name__ == '__main__':
    import asyncio
    from telethon import functions
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人已停止")
