export type Difficulty = 'easy' | 'medium' | 'hard' | 'All';

export type QuestionRecord = {
  id?: string;
  question: string;
  options: string[];
  correct_index: number;
  subject?: string;
  category?: string;
  topic?: string;
  difficulty?: string;
  explanation?: string;
  source?: string;
  added_at?: string;
};

export type ClientQuestion = {
  id: string;
  question: string;
  options: string[];
  subject: string;
  category: string;
  topic: string;
  difficulty: string;
};

export type AnswerKeyEntry = {
  correct_index: number;
  subject: string;
  category: string;
  topic: string;
  difficulty: string;
  explanation: string;
  question: string;
  options: string[];
};

export type Quiz = {
  quiz_id: string;
  duration_minutes: number;
  questions: ClientQuestion[];
  answer_key: Record<string, AnswerKeyEntry>;
  warnings: string[];
};

export type QuizOptions = {
  category: string;
  difficulty: Difficulty;
  topics: string[];
  num_questions: number;
  duration_minutes: number;
};

export type QuizResponse = {
  id: string;
  selected_index: number | null;
  time_spent_seconds: number;
};

export type ReviewItem = AnswerKeyEntry & {
  id: string;
  selected_index: number | null;
  attempted: boolean;
  is_correct: boolean;
  time_spent_seconds: number;
};

export type ScoreResult = {
  score: number;
  total: number;
  attempted: number;
  skipped: number;
  accuracy: number;
  total_time_seconds: number;
  avg_time_seconds: number;
  category_accuracy: Record<string, { correct: number; total: number }>;
  difficulty_accuracy: Record<string, { correct: number; total: number }>;
  topic_accuracy: Record<string, { correct: number; total: number }>;
  review: ReviewItem[];
};

export type SessionRecord = {
  id?: string;
  timestamp?: string;
  mode: string;
  subject: string;
  topics: string[];
  difficulty: string;
  duration_minutes: number;
  score: number;
  total: number;
  accuracy: number;
  attempted: number;
  skipped: number;
  time_taken_seconds: number;
  avg_time_seconds: number;
  category_accuracy: ScoreResult['category_accuracy'];
  difficulty_accuracy: ScoreResult['difficulty_accuracy'];
  topic_accuracy: ScoreResult['topic_accuracy'];
  questions: Array<{
    question: string;
    options: string[];
    correct_index: number;
    selected_index: number | null;
    is_correct: boolean;
    attempted: boolean;
    subject: string;
    topic: string;
    difficulty: string;
    explanation: string;
    time_spent_seconds: number;
  }>;
};

export type ExportPayload = {
  format: 'cgl-buddy-mcq-db';
  version: 1;
  exported_at: string;
  question_count: number;
  questions: QuestionRecord[];
};
