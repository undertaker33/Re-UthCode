import { useEffect, useMemo, useState } from "react";
import type { JsonObject, JsonValue } from "../desktop-api";
import type { PendingInteraction } from "./state";

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

function questionsOf(interaction: PendingInteraction): Question[] {
  const source = asRecord(interaction.request);
  if (!Array.isArray(source.questions)) return [];
  return source.questions.map((value) => asRecord(value)).filter((value): value is Record<string, JsonValue> => typeof value.question_id === "string" && typeof value.question === "string").map((value) => ({
    question_id: String(value.question_id),
    header: String(value.header ?? "Question"),
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
  const questions = useMemo(() => questionsOf(interaction), [interaction]);
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
      <section className="interaction-surface" aria-label="Questions">
        <div className="interaction-surface__header"><div><p className="eyebrow">Input required</p><h2>{review ? "Review answers" : question.header}</h2></div><span>{review ? "Review" : `${step + 1} / ${questions.length}`}</span></div>
        {review ? <div className="answer-review">{questions.map((item) => <div key={item.question_id}><h3>{item.header}</h3><p>{(answers[item.question_id] ?? []).join(", ") || "—"}</p></div>)}</div> : <div className="question-body"><p>{question.question}</p>{question.kind === "text" && <input autoFocus value={selected[0] ?? ""} onChange={(event) => setSelected([event.target.value])} aria-label={question.header} />}{(question.kind === "single_select" || question.kind === "multi_select") && <div className="question-options">{(question.options ?? []).map((option) => <label key={option.label}><input type={question.kind === "single_select" ? "radio" : "checkbox"} name={question.question_id} checked={selected.includes(option.label)} onChange={() => setSelected(question.kind === "single_select" ? [option.label] : selected.includes(option.label) ? selected.filter((item) => item !== option.label) : [...selected, option.label])} /><span><strong>{option.label}</strong><small>{option.description}</small></span></label>)}{question.allow_other && <><label><input type={question.kind === "single_select" ? "radio" : "checkbox"} name={question.question_id} checked={otherSelected} onChange={() => { if (!otherValue) return; setSelected(otherSelected ? selected.filter((item) => item !== otherValue) : question.kind === "single_select" ? [otherValue] : [...selected, otherValue]); }} /><span><strong>Other</strong><small>Provide another answer</small></span></label><input placeholder="Other" value={otherText[question.question_id] ?? ""} onChange={(event) => { const previous = (otherText[question.question_id] ?? "").trim(); const next = event.target.value; const normalizedNext = next.trim(); setOtherText((current) => ({ ...current, [question.question_id]: next })); if (previous && selected.includes(previous)) { if (normalizedNext) setSelected(selected.map((item) => item === previous ? normalizedNext : item)); else setSelected(selected.filter((item) => item !== previous)); } }} aria-label={`${question.header} other`} /></>}</div>}</div>}
        <div className="interaction-actions">{!review && <button type="button" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>Back</button>}{review && <button type="button" onClick={() => setReview(false)}>Edit answers</button>}{!review && step < questions.length - 1 && <button type="button" onClick={() => setStep(step + 1)} disabled={!completeAnswer}>Next</button>}{!review && step === questions.length - 1 && <button type="button" onClick={() => setReview(true)} disabled={!completeAnswer}>Review</button>}{review && <button type="button" className="accent-button" onClick={submit} disabled={interaction.submitting}>Submit answers</button>}<button type="button" className="danger-button" onClick={() => void onCancel()}>Cancel turn</button></div>
      </section>
    );
  }

  if (interaction.kind === "permission_required") {
    const permission = asRecord(request);
    const choices = Array.isArray(permission.choices) ? permission.choices.filter((choice): choice is string => typeof choice === "string") : [];
    const permissionId = typeof permission.permission_id === "string" ? permission.permission_id : "";
    return <section className="interaction-surface" aria-label="Permission approval"><div className="interaction-surface__header"><div><p className="eyebrow">Permission required</p><h2>{String(permission.tool ?? "Tool")}</h2></div><span>{String(permission.action ?? "Review action")}</span></div><p className="interaction-copy">{String(permission.reason ?? "This action needs your approval.")}</p><div className="interaction-actions">{choices.map((choice) => <button type="button" key={choice} className={choice === "reject" ? "danger-button" : "accent-button"} onClick={() => void onSubmit(buildPermissionResponse(interaction, permissionId, choice))} disabled={interaction.submitting}>{choice === "once" ? "Allow once" : choice === "session" ? "Allow for session" : "Reject"}</button>)}</div></section>;
  }

  if (interaction.kind === "plan_review_required") {
    const plan = asRecord(request);
    const revision = typeof plan.revision === "number" ? plan.revision : 1;
    return <section className="interaction-surface" aria-label="Plan review"><div className="interaction-surface__header"><div><p className="eyebrow">Plan review</p><h2>Revision {revision}</h2></div><span>Before execution</span></div><div className="interaction-plan">{String(plan.plan_text ?? "")}</div><div className="interaction-actions"><button type="button" className="accent-button" onClick={() => void onSubmit(buildPlanResponse(interaction, revision, "approve"))} disabled={interaction.submitting}>Approve and execute</button><button type="button" onClick={() => { if (planFeedback.trim()) void onSubmit(buildPlanResponse(interaction, revision, "revise", planFeedback.trim())); }} disabled={interaction.submitting || !planFeedback.trim()}>Revise plan</button><input value={planFeedback} onChange={(event) => setPlanFeedback(event.target.value)} placeholder="Revision feedback" aria-label="Revision feedback" /><button type="button" className="danger-button" onClick={() => void onCancel()}>Cancel turn</button></div></section>;
  }

  if (interaction.kind === "provider_unavailable") return <section className="interaction-surface" aria-label="Provider retry"><div className="interaction-surface__header"><div><p className="eyebrow">Provider unavailable</p><h2>Connection paused</h2></div><span>{interaction.reason ?? "retry"}</span></div><div className="interaction-actions"><button type="button" className="accent-button" onClick={() => void onSubmit(buildRetryResponse(interaction))} disabled={interaction.submitting}>Retry</button><button type="button" className="danger-button" onClick={() => void onCancel()}>Cancel turn</button></div></section>;

  return <section className="interaction-surface" aria-label="Turn paused"><div className="interaction-surface__header"><div><p className="eyebrow">Turn paused</p><h2>Ready to continue</h2></div><span>{interaction.reason ?? "user_requested"}</span></div><div className="interaction-actions"><button type="button" className="accent-button" onClick={() => void onSubmit(buildResumeResponse(interaction))} disabled={interaction.submitting}>Continue</button><button type="button" className="danger-button" onClick={() => void onCancel()}>Cancel turn</button></div></section>;
}
