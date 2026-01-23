-- пользователь
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(25) UNIQUE NOT NULL,
    email VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    rating INTEGER DEFAULT 0,
    role VARCHAR(20) DEFAULT 'user' CHECK(role IN ('user', 'admin', 'moderator')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_enter TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    total_solved INTEGER DEFAULT 0,
    total_attempts INTEGER DEFAULT 0
);

-- предмет
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(20) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(25) --  "info.png", "physics.png"
);

--тема
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    name VARCHAR(25) NOT NULL, --  "кодинг", "тест"
    description TEXT, --написание кода для задачек
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

--задачки
CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    difficulty INTEGER CHECK(difficulty BETWEEN 1 AND 5),
    subject_id INTEGER NOT NULL,
    topic_id INTEGER,
    type VARCHAR(20) DEFAULT 'text',
    correct_answer TEXT, -- ответ
    solution TEXT, -- решение
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(50), --  "ВСОШ, задание 10"

    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

--тесты
CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL,
    input_data TEXT, --входные данные
    output_answer TEXT NOT NULL, -- правильный ответ
    points INTEGER DEFAULT 1, -- баллы

    FOREIGN KEY (problem_id) REFERENCES problems(id) ON DELETE CASCADE
);

-- ответ пользователя
CREATE TABLE IF NOT EXISTS user_solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    problem_id INTEGER NOT NULL,
    answer TEXT NOT NULL,
    is_correct BOOLEAN,
    time_info INTEGER,
    time_of_end TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    points INTEGER DEFAULT 0,
    number_of_tries INTEGER DEFAULT 1,

    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (problem_id) REFERENCES problems(id)
);

--pvp
CREATE TABLE IF NOT EXISTS pvp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    player1_id INTEGER NOT NULL,
    player2_id INTEGER,
    status VARCHAR(15) DEFAULT 'waiting' CHECK(status IN ('error', 'waiting', 'active', 'finished', 'cancelled')),
    problem_ids JSON, --задачки в виде id (5, 12, 8, 15, 3)
    number_of_match INTEGER DEFAULT 0,
    player1_score INTEGER DEFAULT 0,
    player2_score INTEGER DEFAULT 0,
    player1_answers JSON DEFAULT '[]', -- сделать что-то наподобие '[{"answer": "67", "correct": False, "time": 52}]'
    player2_answers JSON DEFAULT '[]',
    time_limit_per_problem INTEGER DEFAULT 120,
    total_problems INTEGER DEFAULT 3,
    match_config JSON, --'{"subject": "info"}'
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    rating_change_player1 INTEGER DEFAULT 0,
    rating_change_player2 INTEGER DEFAULT 0,
    winner_id INTEGER,

    FOREIGN KEY (player1_id) REFERENCES users(id),
    FOREIGN KEY (player2_id) REFERENCES users(id),
    FOREIGN KEY (winner_id) REFERENCES users(id)
);

--очередь на матч
CREATE TABLE IF NOT EXISTS matchmaking_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    subject_id INTEGER,
    min_rating INTEGER,
    max_rating INTEGER,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
);

--статистика
CREATE TABLE IF NOT EXISTS user_topic_stats (
    user_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    solved_count INTEGER DEFAULT 0,
    total_attempts INTEGER DEFAULT 0,
    average_time_on_task REAL,
    last_attempt TIMESTAMP,
    PRIMARY KEY (user_id, topic_id), --  пара (user_id, topic_id)

    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);