import { Component, computed, input } from '@angular/core';
import { Badge } from '../core/hub';

/**
 * A player's hub badges (founder, patron, awards): small colored chips, the name in the tooltip.
 * Cosmetic only. The founder badge reads "#N" when the player has a founder number.
 */
@Component({
  selector: 'ov-badges',
  template: `
    @for (b of list(); track b.id) {
      <span class="hub-badge" [class.hub-badge--founder]="b.kind === 'founder'" [style.--badge-color]="b.color || null"
            [title]="b.title" [attr.aria-label]="b.title" role="img">
        <span aria-hidden="true">{{ b.icon || '★' }}</span>@if (b.number) {<span class="hub-badge__no" aria-hidden="true">#{{ b.number }}</span>}
      </span>
    }
  `,
  host: { class: 'hub-badges' },
})
export class BadgesComponent {
  readonly badges = input<Badge[] | null | undefined>([]);
  readonly founderNo = input<number | null | undefined>(null);
  protected readonly list = computed(() => {
    const no = this.founderNo();
    return (this.badges() ?? []).map((b) => {
      const number = b.kind === 'founder' && no ? no : null;
      const name = number ? `${b.name} #${number}` : b.name;
      return { ...b, number, title: b.description ? `${name}: ${b.description}` : name };
    });
  });
}
