import { useEffect, useMemo, useState } from "react";
import type { JsonObject, JsonValue } from "../desktop-api";
import type { PendingInteraction } from "./state";
import { useTranslation } from "./i18n";

export interface InteractionSurfaceProps {
  interaction: PendingInteraction;
  onSubmit: (response: JsonObject) => void | Promise<void>;
  onCancel: () => void | Promise<void>;
}

export function interactionSurfaceKey(interaction: Pick<PendingInteraction, "pauseId">): string {
  return interaction.pauseId;
}

interface Question {
  question_id: string;
  header: string;
  question: string;
  kind: "text" | "single_select" | "multi_select";
  options?: Array<{ label: string; description: string }>;
  allow_other?: boolean;
}

function asRecord(value: unknown): Record<string, JsonValue> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, JsonValue>;
  return {};
}

function questionsOf(interaction: PendingInteraction, fallbackHeader: string): Question[] {
  const source = asRecord(interaction.request);
  if (!Array.isArray(source.questions)) return [];
  return source.questions.map((value) => asRecord(value)).filter((value): value is Record<string, JsonValue> => typeof value.question_id === "string" && typeof value.question === "string").map((value) => ({
    question_id: String(value.question_id),
    header: String(value.header ?? fallbackHeader),
    question: String(value.question),
    kind: value.kind === "single_select" || value.kind === "multi_select" ? value.kind : "text",
    options: Array.isArray(value.options) ? value.options.map((item) => asRecord(item)).filter((item) => typeof item.label === "string").map((item) => ({ label: String(item.label), description: String(item.description ?? "") })) : [],
    allow_other: value.allow_other === true,
  }));
}

function responseIdentity(interaction: PendingInteraction): JsonObject {
  return {
    pause_id: interaction.pauseId,
    run_id: interaction.runId,
    turn_id: interaction.turnId,
  };
}

export function buildUserInputResponse(interaction: PendingInteraction, answers: Record<string, string[]>): JsonObject {
  return { type: "user_input", ...responseIdentity(interaction), tool_call_id: interaction.toolCallId ?? "", answers };
}

export function buildPermissionResponse(interaction: PendingInteraction, permissionId: string, choice: string): JsonObject {
  return { type: "permission_approval", ...responseIdentity(interaction), permission_id: permissionId, choice };
}

export function buildPlanResponse(interaction: PendingInteraction, revision: number, choice: "approve" | "revise", feedback?: string): JsonObject {
  const result: JsonObject = { type: "plan_review", ...responseIdentity(interaction), revision, choice };
  if (choice === "revise") result.feedback = feedback ?? "";
  return result;
}

export function buildResumeResponse(interaction: PendingInteraction): JsonObject {
  return { type: "resume_turn", ...responseIdentity(interaction) };
}

export function buildRetryResponse(interaction: PendingInteraction): JsonObject {
  return { type: "retry_provider", ...responseIdentity(interaction) };
}

export function InteractionSurface({ interaction, onSubmit, onCancel }: InteractionSurfaceProps) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [step, setStep] = useState(0);
  const [review, setReview] = useState(false);
  const [otherText, setOtherText] = useState<Record<string, string>>({});
  const [planFeedback, setPlanFeedback] = useState("");
  useEffect(() => {
    setAnswers({});
    setStep(0);
    setReview(false);
    setOtherText({});
    setPlanFeedback("");
  }, [interaction.pauseId]);
  const questions = useMemo(() => questionsOf(interaction, t("question")), [interaction, t]);
  const request = asRecord(interaction.request);

  if (interaction.kind === "user_input_required" && questions.length > 0) {
    const question = questions[Math.min(step, questions.length - 1)];
    const selected = answers[question.question_id] ?? [];
    const otherValue = (otherText[question.question_id] ?? "").trim();
    const otherSelected = otherValue.length > 0 && selected.includes(otherValue);
    const setSelected = (values: string[]) => setAnswers((current) => ({ ...current, [question.question_id]: values }));
    const completeAnswer = selected.length > 0 && selected.every((value) => value.trim().length > 0);
    const submit = () => {
      const normalized = Object.fromEntries(questions.map((item) => [item.question_id, answers[item.question_id] ?? []]));
      void onSubmit(buildUserInputResponse(interaction, normalized));
    };
    return (
      <section className="interaction-surface" aria-label={t("questions")}>
        <div className="interaction-surface__header"><div><p className="eyebrow">{t("inputRequired")}</p><h2>{review ? t("reviewAnswers") : question.header}</h2></div><span>{review ? t("review") : `${step + 1} / ${questions.length}`}</span></div>
        {review ? <div className="answer-review">{questions.map((item) => <div key={item.question_id}><h3>{item.header}</h3><p>{(answers[item.question_id] ?? []).join(", ") || "—"}</p></div>)}</div> : <div className="question-body"><p>{question.question}</p>{question.kind === "text" && <input autoFocus value={selected[0] ?? ""} onChange={(event) => setSelected([event.target.value])} aria-label={question.header} />}{(question.kind === "single_select" || question.kind === "multi_select") && <div className="question-options">{(question.options ?? []).map((option) => <label key={option.label}><input type={question.kind === "single_select" ? "radio" : "checkbox"} name={question.question_id} checked={selected.includes(option.label)} onChange={() => setSelected(question.kind === "single_select" ? [option.label] : selected.includes(option.label) ? selected.filter((item) => item !== option.label) : [...selected, option.label])} /><span><strong>{option.label}</strong><small>{option.description}</small></span></label>)}{question.allow_other && <><label><input type={question.kind === "single_select" ? "radio" : "checkbox"} name={question.question_id} checked={otherSelected} onChange={() => { if (!otherValue) return; setSelected(otherSelected ? selected.filter((item) => item !== otherValue) : question.kind === "single_select" ? [otherValue] : [...selected, otherValue]); }} /><span><strong>{t("other")}</strong><small>{t("provideAnotherAnswer")}</small></span></label><input placeholder={t("other")} value={otherText[question.question_id] ?? ""} onChange={(event) => { const previous = (otherText[question.question_id] ?? "").trim(); const next = event.target.value; const normalizedNext = next.trim(); setOtherText((current) => ({ ...current, [question.question_id]: next })); if (previous && selected.includes(previous)) { if (normalizedNext) setSelected(selected.map((item) => item === previous ? normalizedNext : item)); else setSelected(selected.filter((item) => item !== previous)); } }} aria-label={`${question.header} ${t("other")}`} /></>}</div>}</div>}
        <div className="interaction-actions">{!review && <button type="button" title={t("back")} onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>{t("back")}</button>}{review && <button type="button" title={t("editAnswers")} onClick={() => setReview(false)}>{t("editAnswers")}</button>}{!review && step < questions.length - 1 && <button type="button" title={t("next")} onClick={() => setStep(step + 1)} disabled={!completeAnswer}>{t("next")}</button>}{!review && step === questions.length - 1 && <button type="button" title={t("review")} onClick={() => setReview(true)} disabled={!completeAnswer}>{t("review")}</button>}{review && <button type="button" className="accent-button" title={t("submitAnswers")} onClick={submit} disabled={interaction.submitting}>{t("submitAnswers")}</button>}<button type="button" className="danger-button" title={t("cancelTurn")} onClick={() => void onCancel()}>{t("cancelTurn")}</button></div>
      </section>
    );
  }

  if (interaction.kind === "permission_required") {
    const permission = asRecord(request);
    const choices = Array.isArray(permission.choices) ? permission.choices.filter((choice): choice is string => typeof choice === "string") : [];
    const permissionId = typeof permission.permission_id === "string" ? permission.permission_id : "";
    return <section className="interaction-surface" aria-label={t("permissionApproval")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("permissionRequired")}</p><h2>{String(permission.tool ?? t("tool"))}</h2></div><span>{String(permission.action ?? t("reviewAction"))}</span></div><p className="interaction-copy">{String(permission.reason ?? t("approvalReason"))}</p><div className="interaction-actions">{choices.map((choice) => <button type="button" title={choice === "once" ? t("allowOnce") : choice === "session" ? t("allowSession") : t("reject")} key={choice} className={choice === "reject" ? "danger-button" : "accent-button"} onClick={() => void onSubmit(buildPermissionResponse(interaction, permissionId, choice))} disabled={interaction.submitting}>{choice === "once" ? t("allowOnce") : choice === "session" ? t("allowSession") : t("reject")}</button>)}</div></section>;
  }

  if (interaction.kind === "plan_review_required") {
    const plan = asRecord(request);
    const revision = typeof plan.revision === "number" ? plan.revision : 1;
    return <section className="interaction-surface" aria-label={t("planReview")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("planReview")}</p><h2>{t("revision")} {revision}</h2></div><span>{t("beforeExecution")}</span></div><div className="interaction-plan">{String(plan.plan_text ?? "")}</div><div className="interaction-actions"><button type="button" title={t("approve")} className="accent-button" onClick={() => void onSubmit(buildPlanResponse(interaction, revision, "approve"))} disabled={interaction.submitting}>{t("approve")}</button><button type="button" title={t("revise")} onClick={() => { if (planFeedback.trim()) void onSubmit(buildPlanResponse(interaction, revision, "revise", planFeedback.trim())); }} disabled={interaction.submitting || !planFeedback.trim()}>{t("revise")}</button><input value={planFeedback} onChange={(event) => setPlanFeedback(event.target.value)} placeholder={t("revisionFeedback")} aria-label={t("revisionFeedback")} /><button type="button" title={t("cancelTurn")} className="danger-button" onClick={() => void onCancel()}>{t("cancelTurn")}</button></div></section>;
  }

  if (interaction.kind === "provider_unavailable") return <section className="interaction-surface" aria-label={t("providerRetry")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("providerUnavailable")}</p><h2>{t("connectionPaused")}</h2></div><span>{interaction.reason ?? "retry"}</span></div><div className="interaction-actions"><button type="button" title={t("retry")} className="accent-button" onClick={() => void onSubmit(buildRetryResponse(interaction))} disabled={interaction.submitting}>{t("retry")}</button><button type="button" title={t("cancelTurn")} className="danger-button" onClick={() => void onCancel()}>{t("cancelTurn")}</button></div></section>;

  return <section className="interaction-surface" aria-label={t("turnPaused")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("turnPaused")}</p><h2>{t("readyToContinue")}</h2></div><span>{interaction.reason ?? "user_requested"}</span></div><div className="interaction-actions"><button type="button" title={t("continue")} className="accent-button" onClick={() => void onSubmit(buildResumeResponse(interaction))} disabled={interaction.submitting}>{t("continue")}</button><button type="button" title={t("cancelTurn")} className="danger-button" onClick={() => void onCancel()}>{t("cancelTurn")}</button></div></section>;
}
