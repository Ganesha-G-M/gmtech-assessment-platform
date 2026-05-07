ALTER TABLE questions
ADD COLUMN question_type VARCHAR(20) NOT NULL DEFAULT 'mcq',
ADD COLUMN language_id INT NULL,
ADD COLUMN starter_code TEXT NULL;

CREATE TABLE IF NOT EXISTS coding_test_cases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    question_id INT NOT NULL,
    input_data TEXT,
    expected_output TEXT NOT NULL,
    is_hidden TINYINT(1) NOT NULL DEFAULT 0,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);
