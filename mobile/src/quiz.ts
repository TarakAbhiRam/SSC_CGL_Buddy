import type { AnswerKeyEntry, QuestionRecord, Quiz, QuizOptions, QuizResponse, ScoreResult } from './types';
import { loadBundledQuestions, storedQuestions } from './storage';

export const SUBJECTS = [
  'General Intelligence & Reasoning',
  'Quantitative Aptitude',
  'English Comprehension',
  'General Awareness',
];

function newId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
}

function subjectOf(question: QuestionRecord): string {
  return String(question.subject || question.category || 'General');
}

function shuffle<T>(items: T[]): T[] {
  const out = [...items];
  for (let index = out.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1));
    [out[index], out[swap]] = [out[swap], out[index]];
  }
  return out;
}

function filterQuestions(questions: QuestionRecord[], options: QuizOptions): QuestionRecord[] {
  return questions.filter((question) => {
    if (options.category && options.category !== 'All' && subjectOf(question) !== options.category) return false;
    if (options.difficulty && options.difficulty !== 'All' && question.difficulty !== options.difficulty) return false;
    if (options.topics.length && !options.topics.includes(String(question.topic || ''))) return false;
    return true;
  });
}

export async function allQuestions(): Promise<QuestionRecord[]> {
  return [...await loadBundledQuestions(), ...await storedQuestions()];
}

export async function listCategories(): Promise<string[]> {
  const present = new Set((await allQuestions()).map(subjectOf));
  return ['All', ...SUBJECTS.filter((subject) => present.has(subject))];
}

export async function listTopics(subject: string): Promise<string[]> {
  if (!subject || subject === 'All') return [];
  const topics = new Set(
    (await allQuestions())
      .filter((question) => subjectOf(question) === subject && question.topic)
      .map((question) => String(question.topic)),
  );
  return [...topics].sort((a, b) => a.localeCompare(b));
}

export async function bankCount(options: QuizOptions): Promise<number> {
  return filterQuestions(await allQuestions(), options).length;
}

export async function startQuiz(options: QuizOptions): Promise<Quiz> {
  const pool = filterQuestions(await allQuestions(), options);
  const selected = shuffle(pool).slice(0, Math.max(0, options.num_questions));
  const answerKey: Record<string, AnswerKeyEntry> = {};
  const clientQuestions = selected.map((question) => {
    const id = newId();
    const subject = subjectOf(question);
    answerKey[id] = {
      correct_index: Number(question.correct_index),
      subject,
      category: subject,
      topic: String(question.topic || ''),
      difficulty: String(question.difficulty || 'medium'),
      explanation: String(question.explanation || ''),
      question: question.question,
      options: question.options,
    };
    return {
      id,
      question: question.question,
      options: question.options,
      subject,
      category: subject,
      topic: String(question.topic || ''),
      difficulty: String(question.difficulty || 'medium'),
    };
  });

  const warnings = selected.length < options.num_questions
    ? [`Only ${selected.length} matching question${selected.length === 1 ? '' : 's'} found for the selected filters.`]
    : [];

  return {
    quiz_id: newId(),
    duration_minutes: options.duration_minutes,
    questions: clientQuestions,
    answer_key: answerKey,
    warnings,
  };
}

function addStat(bucket: Record<string, { correct: number; total: number }>, key: string, correct: boolean): void {
  const stat = bucket[key] || { correct: 0, total: 0 };
  stat.total += 1;
  if (correct) stat.correct += 1;
  bucket[key] = stat;
}

export function scoreQuiz(answerKey: Record<string, AnswerKeyEntry>, responses: QuizResponse[]): ScoreResult {
  const byId = new Map(responses.map((response) => [response.id, response]));
  let correct = 0;
  let attempted = 0;
  let totalTime = 0;
  const category_accuracy: ScoreResult['category_accuracy'] = {};
  const difficulty_accuracy: ScoreResult['difficulty_accuracy'] = {};
  const topic_accuracy: ScoreResult['topic_accuracy'] = {};
  const review = Object.entries(answerKey).map(([id, key]) => {
    const response = byId.get(id);
    const selected = response?.selected_index ?? null;
    const time = Number(response?.time_spent_seconds || 0);
    totalTime += time;
    const wasAttempted = selected !== null;
    const isCorrect = wasAttempted && selected === key.correct_index;
    if (wasAttempted) attempted += 1;
    if (isCorrect) correct += 1;
    addStat(category_accuracy, key.subject || 'General', isCorrect);
    addStat(difficulty_accuracy, key.difficulty || 'medium', isCorrect);
    addStat(topic_accuracy, key.topic || 'General', isCorrect);
    return {
      ...key,
      id,
      selected_index: selected,
      attempted: wasAttempted,
      is_correct: isCorrect,
      time_spent_seconds: time,
    };
  });
  const total = review.length;
  return {
    score: correct,
    total,
    attempted,
    skipped: Math.max(0, total - attempted),
    accuracy: total ? Math.round((correct / total) * 1000) / 10 : 0,
    total_time_seconds: totalTime,
    avg_time_seconds: total ? totalTime / total : 0,
    category_accuracy,
    difficulty_accuracy,
    topic_accuracy,
    review,
  };
}
