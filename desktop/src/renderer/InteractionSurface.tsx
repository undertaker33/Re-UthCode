import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
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
  }));
}

function responseIdentity(interaction: PendingInteraction): JsonObject {
  return {
    pause_id: interaction.pauseId,
    run_id: interaction.runId,
    turn_id: interaction.turnId,
  };
}

const FOCUSABLE_SELECTOR = "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((element) => element.getAttribute("aria-hidden") !== "true");
}

interface SavedBackgroundState {
  element: HTMLElement;
  inert: boolean;
  ariaHidden: string | null;
}

/** Inert every ancestor sibling of the dialog, including app chrome and test-host siblings. */
function inertBackground(surface: HTMLElement): SavedBackgroundState[] {
  const saved: SavedBackgroundState[] = [];
  let branch: Element = surface;
  let parent = surface.parentElement;
  while (parent) {
    for (const sibling of Array.from(parent.children)) {
      if (sibling === branch || !(sibling instanceof HTMLElement)) continue;
      const element = sibling as HTMLElement & { inert?: boolean };
      saved.push({ element, inert: element.inert === true, ariaHidden: element.getAttribute("aria-hidden") });
      element.inert = true;
      element.setAttribute("aria-hidden", "true");
    }
    branch = parent;
    parent = parent.parentElement;
  }
  return saved;
}

function restoreBackground(saved: SavedBackgroundState[]): void {
  for (const { element, inert, ariaHidden } of saved) {
    (element as HTMLElement & { inert?: boolean }).inert = inert;
    if (ariaHidden === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", ariaHidden);
  }
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
  const [freeText, setFreeText] = useState<Record<string, string>>({});
  const [planFeedback, setPlanFeedback] = useState("");
  const freeTextRef = useRef<Record<string, string>>({});
  const submitLock = useRef(false);
  const surfaceRef = useRef<HTMLElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const questions = useMemo(() => questionsOf(interaction, t("question")), [interaction, t]);
  const request = asRecord(interaction.request);
  const activeQuestionId = questions[Math.min(step, Math.max(questions.length - 1, 0))]?.question_id ?? "";
  useEffect(() => {
    setAnswers({});
    setStep(0);
    setReview(false);
    setFreeText({});
    freeTextRef.current = {};
    submitLock.current = false;
    setPlanFeedback("");
  }, [interaction.pauseId]);
  useEffect(() => {
    if (!interaction.submitting) submitLock.current = false;
  }, [interaction.submitting]);
  const submitResponse = (response: JsonObject) => {
    if (interaction.submitting || submitLock.current) return;
    submitLock.current = true;
    void onSubmit(response);
  };
  const cancelInteraction = () => {
    // A response is already in flight; cancellation would create a second
    // competing resume/cancel request for the same Pause identity.
    if (interaction.submitting || submitLock.current) return;
    void onCancel();
  };
  const handleSurfaceKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (interaction.submitting || submitLock.current) return;
      cancelInteraction();
      return;
    }
    if (event.key !== "Tab") return;
    const surface = surfaceRef.current;
    if (!surface) return;
    const focusable = focusableElements(surface);
    if (!focusable.length) {
      event.preventDefault();
      surface.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const current = document.activeElement;
    if (event.shiftKey && (current === first || !focusable.includes(current as HTMLElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (current === last || !focusable.includes(current as HTMLElement))) {
      event.preventDefault();
      first.focus();
    }
  };
  const modalProps = { ref: surfaceRef, tabIndex: -1, onKeyDown: handleSurfaceKeyDown, "aria-busy": interaction.submitting || undefined };
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const surface = surfaceRef.current;
    const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // A keyed interaction replacement can mount while the old dialog still
    // owns focus.  That dialog is about to disappear, so keep the persistent
    // Composer as the restore target instead of retaining a dead control.
    previousFocusRef.current = active && !active.closest('[role="dialog"]')
      ? active
      : document.querySelector<HTMLElement>(".composer textarea");
    const blocked = surface ? inertBackground(surface) : [];
    return () => {
      restoreBackground(blocked);
      const previous = previousFocusRef.current;
      if (previous?.isConnected) {
        previous.focus();
      } else {
        // Inputs in this surface may have autoFocus, so the captured element
        // can be the soon-to-be-removed dialog control. Return focus to the
        // persistent Composer when the interaction closes.
        document.querySelector<HTMLElement>(".composer textarea")?.focus();
      }
      previousFocusRef.current = null;
    };
  }, [interaction.pauseId]);
  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    // Review and question navigation replace the focusable controls in place;
    // move focus into the new view instead of leaving it on a removed button or
    // an auto-focused field from the previous question.
    const focusable = focusableElements(surface);
    const preferred = review
      ? focusable[0]
      : surface.querySelector<HTMLElement>(".question-free-input") ?? focusable[0];
    preferred?.focus();
  }, [activeQuestionId, interaction.kind, interaction.pauseId, review, step]);

  if (interaction.kind === "user_input_required" && questions.length > 0) {
    const question = questions[Math.min(step, questions.length - 1)];
    const selected = answers[question.question_id] ?? [];
    const freeValue = freeText[question.question_id] ?? "";
    const setSelected = (values: string[]) => {
      setAnswers((current) => ({ ...current, [question.question_id]: values }));
      if (question.kind === "single_select") {
        setFreeText((current) => ({ ...current, [question.question_id]: "" }));
      }
    };
    const setFreeValue = (value: string) => {
      const previous = (freeTextRef.current[question.question_id] ?? "").trim();
      freeTextRef.current = { ...freeTextRef.current, [question.question_id]: value };
      setFreeText((current) => ({ ...current, [question.question_id]: value }));
      setAnswers((current) => {
        const withoutPrevious = (current[question.question_id] ?? []).filter((item) => item !== previous);
        const normalized = value.trim();
        if (question.kind === "single_select") {
          return { ...current, [question.question_id]: normalized ? [normalized] : [] };
        }
        return { ...current, [question.question_id]: normalized ? [...withoutPrevious, normalized] : withoutPrevious };
      });
    };
    const completeAnswer = selected.length > 0 && selected.every((value) => value.trim().length > 0);
    const submit = () => {
      if (interaction.submitting || submitLock.current) return;
      const normalized = Object.fromEntries(questions.map((item) => [item.question_id, answers[item.question_id] ?? []]));
      submitResponse(buildUserInputResponse(interaction, normalized));
    };
    return (
      <section {...modalProps} className="interaction-surface" role="dialog" aria-modal="true" aria-label={t("questions")}>
        <div className="interaction-surface__header"><div><p className="eyebrow">{t("inputRequired")}</p><h2>{review ? t("reviewAnswers") : question.header}</h2></div><span aria-live="polite">{review ? t("review") : `${step + 1} / ${questions.length}`}</span></div>
        {review ? <div className="answer-review">{questions.map((item) => <div key={item.question_id}><h3>{item.header}</h3><p>{(answers[item.question_id] ?? []).join(", ") || "—"}</p></div>)}</div> : <div className="question-body" aria-live="polite"><p>{question.question}</p>{question.kind === "text" && <input autoFocus value={selected[0] ?? ""} onChange={(event) => setSelected([event.target.value])} aria-label={question.header} />}{(question.kind === "single_select" || question.kind === "multi_select") && <div className="question-options">{(question.options ?? []).map((option) => <label key={option.label}><input type={question.kind === "single_select" ? "radio" : "checkbox"} name={question.question_id} checked={selected.includes(option.label)} onChange={() => setSelected(question.kind === "single_select" ? [option.label] : selected.includes(option.label) ? selected.filter((item) => item !== option.label) : [...selected, option.label])} /><span><strong>{option.label}</strong><small>{option.description}</small></span></label>)}<input className="question-free-input" autoFocus value={freeValue} placeholder={t("provideAnotherAnswer")} onChange={(event) => setFreeValue(event.target.value)} aria-label={`${question.header} ${t("provideAnotherAnswer")}`} /></div>}</div>}
        <div className="interaction-actions">{!review && <button type="button" title={t("previous")} onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0 || interaction.submitting}>{t("previous")}</button>}{review && <button type="button" title={t("editAnswers")} onClick={() => setReview(false)} disabled={interaction.submitting}>{t("editAnswers")}</button>}{!review && step < questions.length - 1 && <button type="button" title={t("next")} onClick={() => setStep(step + 1)} disabled={!completeAnswer || interaction.submitting}>{t("next")}</button>}{!review && step === questions.length - 1 && <button type="button" title={t("review")} onClick={() => setReview(true)} disabled={!completeAnswer || interaction.submitting}>{t("review")}</button>}{review && <button type="button" className="accent-button" title={t("submitAnswers")} onClick={submit} disabled={interaction.submitting}>{t("submitAnswers")}</button>}<button type="button" className="danger-button" title={t("cancelTurn")} onClick={cancelInteraction} disabled={interaction.submitting}>{t("cancelTurn")}</button></div>
      </section>
    );
  }

  if (interaction.kind === "permission_required") {
    const permission = asRecord(request);
    const choices = Array.isArray(permission.choices) ? permission.choices.filter((choice): choice is string => typeof choice === "string") : [];
    const permissionId = typeof permission.permission_id === "string" ? permission.permission_id : "";
    return <section {...modalProps} className="interaction-surface" role="dialog" aria-modal="true" aria-label={t("permissionApproval")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("permissionRequired")}</p><h2>{String(permission.tool ?? t("tool"))}</h2></div><span>{String(permission.action ?? t("reviewAction"))}</span></div><p className="interaction-copy">{String(permission.reason ?? t("approvalReason"))}</p><div className="interaction-actions">{choices.map((choice) => <button type="button" title={choice === "once" ? t("allowOnce") : choice === "session" ? t("allowSession") : t("reject")} key={choice} className={choice === "reject" ? "danger-button" : "accent-button"} onClick={() => submitResponse(buildPermissionResponse(interaction, permissionId, choice))} disabled={interaction.submitting}>{choice === "once" ? t("allowOnce") : choice === "session" ? t("allowSession") : t("reject")}</button>)}</div></section>;
  }

  if (interaction.kind === "plan_review_required") {
    const plan = asRecord(request);
    const revision = typeof plan.revision === "number" ? plan.revision : 1;
    return <section {...modalProps} className="interaction-surface" role="dialog" aria-modal="true" aria-label={t("planReview")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("planReview")}</p><h2>{t("revision")} {revision}</h2></div><span>{t("beforeExecution")}</span></div><div className="interaction-plan">{String(plan.plan_text ?? "")}</div><div className="interaction-actions"><button type="button" title={t("approve")} className="accent-button" onClick={() => submitResponse(buildPlanResponse(interaction, revision, "approve"))} disabled={interaction.submitting}>{t("approve")}</button><button type="button" title={t("revise")} onClick={() => { if (planFeedback.trim()) submitResponse(buildPlanResponse(interaction, revision, "revise", planFeedback.trim())); }} disabled={interaction.submitting || !planFeedback.trim()}>{t("revise")}</button><input value={planFeedback} onChange={(event) => setPlanFeedback(event.target.value)} placeholder={t("revisionFeedback")} aria-label={t("revisionFeedback")} disabled={interaction.submitting} /><button type="button" title={t("cancelTurn")} className="danger-button" onClick={cancelInteraction} disabled={interaction.submitting}>{t("cancelTurn")}</button></div></section>;
  }

  if (interaction.kind === "provider_unavailable") return <section {...modalProps} className="interaction-surface" role="dialog" aria-modal="true" aria-label={t("providerRetry")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("providerUnavailable")}</p><h2>{t("connectionPaused")}</h2></div><span>{interaction.reason ?? "retry"}</span></div><div className="interaction-actions"><button type="button" title={t("retry")} className="accent-button" onClick={() => submitResponse(buildRetryResponse(interaction))} disabled={interaction.submitting}>{t("retry")}</button><button type="button" title={t("cancelTurn")} className="danger-button" onClick={cancelInteraction} disabled={interaction.submitting}>{t("cancelTurn")}</button></div></section>;

  return <section {...modalProps} className="interaction-surface" role="dialog" aria-modal="true" aria-label={t("turnPaused")}><div className="interaction-surface__header"><div><p className="eyebrow">{t("turnPaused")}</p><h2>{t("readyToContinue")}</h2></div><span>{interaction.reason ?? "user_requested"}</span></div><div className="interaction-actions"><button type="button" title={t("continue")} className="accent-button" onClick={() => submitResponse(buildResumeResponse(interaction))} disabled={interaction.submitting}>{t("continue")}</button><button type="button" title={t("cancelTurn")} className="danger-button" onClick={cancelInteraction} disabled={interaction.submitting}>{t("cancelTurn")}</button></div></section>;
}
