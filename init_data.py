# init_data.py (放在 your_project_root/ 下)
from shared_lib.models import SessionLocal, Bot, GuildConfig, Guild  # 确保 Guild 被导入！
from shared_lib.crud import DEFAULT_BOT_ID

# 强制创建所有表（包括 guilds）
from shared_lib.models import Base, engine
Base.metadata.create_all(engine)
print("📋 所有数据表已创建完成（包含 guilds）")

session = SessionLocal()

# 1. 插入默认机器人（如果不存在）
if not session.query(Bot).filter_by(bot_id=DEFAULT_BOT_ID).first():
    session.add(Bot(bot_id=DEFAULT_BOT_ID, bot_name="默认机器人"))
    session.commit()
    print("✅ 默认机器人已插入")

# 2. 插入几条演示配置（仅当表为空时）
if session.query(GuildConfig).count() == 0:
    test_configs = [
        (DEFAULT_BOT_ID, "guild_123", "welcome_msg", "欢迎来到服务器A！"),
        (DEFAULT_BOT_ID, "guild_456", "welcome_msg", "欢迎来到服务器B！"),
        (DEFAULT_BOT_ID, "guild_123", "log_channel", "987654321"),
    ]
    for bot_id, guild_id, key, val in test_configs:
        session.add(GuildConfig(bot_id=bot_id, guild_id=guild_id, config_key=key, config_value=val))
    session.commit()
    print("✅ 测试配置数据已插入")

session.close()
print("🎉 所有初始化完成！")