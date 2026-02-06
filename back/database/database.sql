-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    rating INTEGER DEFAULT 1000,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    banned_by INTEGER,
    banned_at TEXT,
    ban_reason TEXT,
    solved_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    subject_stats TEXT DEFAULT '{}',
    last_login TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица задач
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    topic TEXT,
    question TEXT NOT NULL,
    options TEXT NOT NULL,
    answer TEXT NOT NULL,
    hint TEXT DEFAULT '',
    created_by INTEGER,
    generated_by_llm INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

-- Таблица матчей
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player1_id INTEGER,
    player1_name TEXT,
    player1_rating INTEGER,
    player2_id INTEGER,
    player2_name TEXT,
    player2_rating INTEGER,
    subject TEXT,
    mode TEXT,
    tasks TEXT,
    is_bot INTEGER DEFAULT 0,
    event_id INTEGER,
    event_round INTEGER,
    player1_score INTEGER DEFAULT 0,
    player2_score INTEGER DEFAULT 0,
    player1_answers TEXT DEFAULT '[]',
    player2_answers TEXT DEFAULT '[]',
    current_task INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    cancel_reason TEXT,
    cancelled_by INTEGER,
    cancelled_at TEXT,
    finished_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица очереди матчмейкинга
CREATE TABLE IF NOT EXISTS matchmaking_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    user_rating INTEGER,
    subject TEXT,
    mode TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица истории пользователя
CREATE TABLE IF NOT EXISTS user_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action_text TEXT,
    action_date TEXT,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

-- Таблица истории матчей пользователя
CREATE TABLE IF NOT EXISTS user_match_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    match_id INTEGER,
    opponent_name TEXT,
    opponent_rating INTEGER,
    my_score INTEGER,
    opp_score INTEGER,
    result TEXT,
    rating_change INTEGER,
    subject TEXT,
    mode TEXT,
    match_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица достижений пользователей
CREATE TABLE IF NOT EXISTS user_achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    achievement_id TEXT NOT NULL,
    earned_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, achievement_id)
);

-- Таблица дневной статистики
CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stat_date TEXT NOT NULL,
    day_of_week TEXT,
    subject TEXT DEFAULT 'all',
    solved INTEGER DEFAULT 0,
    correct INTEGER DEFAULT 0,
    UNIQUE(user_id, stat_date, subject)
);

-- Таблица событий (марафоны/турниры)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    rules TEXT DEFAULT '{}',
    max_participants INTEGER DEFAULT 100,
    current_participants INTEGER DEFAULT 0,
    prizes TEXT DEFAULT '{}',
    status TEXT DEFAULT 'upcoming',
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица участников событий
CREATE TABLE IF NOT EXISTS event_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER DEFAULT 0,
    tasks_solved INTEGER DEFAULT 0,
    tasks_correct INTEGER DEFAULT 0,
    matches_played INTEGER DEFAULT 0,
    matches_won INTEGER DEFAULT 0,
    stats TEXT DEFAULT '{}',
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_id, user_id)
);

-- Таблица активности в марафонах
CREATE TABLE IF NOT EXISTS marathon_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    activity_type TEXT,
    points_earned INTEGER DEFAULT 0,
    details TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица матчей турниров
CREATE TABLE IF NOT EXISTS tournament_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    round_num INTEGER NOT NULL,
    player1_id INTEGER,
    player2_id INTEGER,
    match_id INTEGER,
    winner_id INTEGER,
    status TEXT DEFAULT 'pending'
);

-- Таблица логов админов
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    details TEXT DEFAULT '{}',
    ip_address TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Таблица настроек
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    description TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_rating ON users(rating DESC);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_tasks_subject ON tasks(subject);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_player1 ON matches(player1_id);
CREATE INDEX IF NOT EXISTS idx_matches_player2 ON matches(player2_id);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_daily_stats_user ON daily_stats(user_id);