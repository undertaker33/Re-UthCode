import { useEffect, useId, useRef, useState } from "react";

export interface SelectOption { value: string; label: string; disabled?: boolean }
export interface CustomSelectProps { value: string; options: readonly SelectOption[]; onChange: (value: string) => void; label: string; disabled?: boolean; id?: string; onOpen?: () => void }
export function nextEnabledOption(options: readonly SelectOption[], current: number, step: 1 | -1): number {
  let next = current;
  for (let count = 0; count < options.length; count += 1) { next = (next + step + options.length) % options.length; if (!options[next]?.disabled) return next; }
  return current;
}
export function initialEnabledOption(options: readonly SelectOption[], value: string): number {
  const selected = options.findIndex((item) => item.value === value && !item.disabled);
  return selected >= 0 ? selected : options.findIndex((item) => !item.disabled);
}
export function customSelectConsumesEscape(open: boolean): boolean { return open; }

export function CustomSelect({ value, options, onChange, label, disabled = false, id, onOpen }: CustomSelectProps) {
  const generatedId = useId();
  const listId = `${id ?? generatedId}-listbox`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => initialEnabledOption(options, value));
  const [placement, setPlacement] = useState<"above" | "below">("above");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const optionSignature = options.map((option) => `${option.value}\u0000${option.label}\u0000${option.disabled ? "1" : "0"}`).join("\u0001");
  useEffect(() => { if (!open) setActive(initialEnabledOption(options, value)); }, [open, optionSignature, value]);
  useEffect(() => { if (open && active >= 0) optionRefs.current[active]?.focus(); }, [open, active]);
  useEffect(() => {
    if (!disabled || !open) return;
    setOpen(false);
    trigger.current?.blur();
  }, [disabled, open]);
  const updatePlacement = () => {
    const element = trigger.current;
    if (!element || typeof window === "undefined") return;
    const rect = element.getBoundingClientRect();
    // JSDOM and hidden shells expose a zero rectangle; retain the product
    // default (upward) until real geometry is available.
    if (rect.top === 0 && rect.bottom === 0 && rect.height === 0) {
      setPlacement("above");
      return;
    }
    const estimatedHeight = Math.min(320, Math.max(44, options.length * 38 + 10));
    const spaceAbove = Math.max(0, rect.top);
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom);
    setPlacement(spaceAbove >= estimatedHeight || spaceAbove >= spaceBelow ? "above" : "below");
  };
  useEffect(() => {
    if (!open) return undefined;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) { setOpen(false); trigger.current?.focus(); } };
    updatePlacement();
    document.addEventListener("pointerdown", close);
    window.addEventListener("resize", updatePlacement);
    window.addEventListener("scroll", updatePlacement, true);
    return () => { document.removeEventListener("pointerdown", close); window.removeEventListener("resize", updatePlacement); window.removeEventListener("scroll", updatePlacement, true); };
  }, [open, options.length]);
  const closeMenu = (restoreFocus = false) => { setOpen(false); if (restoreFocus) trigger.current?.focus(); };
  const openMenu = () => { onOpen?.(); updatePlacement(); setOpen(true); };
  const choose = (index: number) => { const option = options[index]; if (!option || option.disabled) return; onChange(option.value); closeMenu(true); };
  const move = (step: 1 | -1) => setActive((current) => nextEnabledOption(options, current, step));
  const edge = (last: boolean) => { const indices = options.map((option, index) => option.disabled ? -1 : index).filter((index) => index >= 0); setActive(last ? indices.at(-1) ?? -1 : indices[0] ?? -1); };
  const keyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { if (!customSelectConsumesEscape(open)) return; event.preventDefault(); event.stopPropagation(); closeMenu(true); return; }
    if (event.key === "Tab") { closeMenu(); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); event.stopPropagation(); if (!open) openMenu(); else move(event.key === "ArrowDown" ? 1 : -1); return; }
    if (open && (event.key === "Home" || event.key === "End")) { event.preventDefault(); event.stopPropagation(); edge(event.key === "End"); return; }
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); if (open) choose(active); else openMenu(); }
  };
  const selected = options.find((item) => item.value === value);
  return <div className="custom-select" ref={root} onKeyDown={keyDown} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) closeMenu(); }}>
    <button ref={trigger} id={id} type="button" className="custom-select__trigger" title={label} aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} disabled={disabled} onClick={() => { if (open) closeMenu(); else openMenu(); }}>{selected?.label ?? value}<span aria-hidden="true">⌄</span></button>
    {open && <div id={listId} className={`custom-select__list is-${placement}`} role="listbox" aria-label={label}>{options.map((option, index) => <button ref={(element) => { optionRefs.current[index] = element; }} id={`${listId}-option-${index}`} type="button" role="option" title={option.label} key={option.value} aria-selected={option.value === value} tabIndex={index === active ? 0 : -1} className={index === active ? "is-active" : ""} disabled={option.disabled} onPointerMove={() => { if (!option.disabled) setActive(index); }} onClick={() => choose(index)}>{option.label}</button>)}</div>}
  </div>;
}
