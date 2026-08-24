<script setup lang="ts">
/** The project's event log, on a URL of its own (PX-64). Formerly `?tab=activity`. */
import UiButton from "../../../components/ui/UiButton.vue";
import UiCard from "../../../components/ui/UiCard.vue";
import { useProjectsStore } from "../../../stores/projects";
import { kindLabel } from "../../../utils/activityKinds";
import { formatInstant } from "../../../utils/time";
import { describeActivity } from "../describeActivity";
import { useProjectContext } from "../useProjectContext";

const { projectId } = useProjectContext();
const projects = useProjectsStore();
</script>

<template>
  <section class="tab-panel activity-panel">
    <!--
      Stated, never left blank. A missing actor means one of two different things — a
      system-originated event, or a reader without `audit.view` — and silence would let
      the second read as the first.
    -->
    <p v-if="projects.actorsHidden" class="notice muted">
      Some information is hidden: showing who performed an action requires audit
      permission.
    </p>
    <UiCard flush>
      <template #header>
        <div class="card-heading">
          <div>
            <span>Activity log</span>
            <small>Project, workspace and session events in time order.</small>
          </div>
        </div>
      </template>
      <ul class="timeline activity-log">
        <li v-for="event in projects.activity" :key="event.id">
          <span class="when" :title="event.occurred_at">
            {{ formatInstant(event.occurred_at) }}
          </span>
          <span class="what">{{ kindLabel(event.kind) }}</span>
          <span class="detail">{{
            describeActivity(event.kind, event.payload)
          }}</span>
          <span class="who">{{ event.actor_name ?? "—" }}</span>
        </li>
      </ul>
    </UiCard>
    <UiButton
      v-if="projects.activityCursor"
      variant="secondary"
      @click="projects.fetchActivity(projectId, { append: true })"
    >
      Load more
    </UiButton>
  </section>
</template>

<style scoped>
.tab-panel {
  display: grid;
  gap: var(--space-4);
}
.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  font-size: var(--font-sm);
}
.card-heading > div {
  display: grid;
  gap: 2px;
}
.card-heading small,
.heading-note {
  color: var(--text-muted);
  font-size: var(--font-xs);
  font-weight: 400;
}
.card-empty {
  margin: 0;
  padding: var(--space-5) var(--space-4);
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.bindings,
.timeline {
  border: 0;
  border-radius: 0;
  background: transparent;
}
.bindings li,
.timeline li {
  min-height: 46px;
  padding: var(--space-3) var(--space-4);
}
.timeline li {
  position: relative;
  padding-left: var(--space-5);
}
.timeline li::before {
  position: absolute;
  left: var(--space-3);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  content: "";
  background: var(--action-primary);
}
.activity-log:empty::after {
  display: block;
  padding: var(--space-5);
  color: var(--text-muted);
  content: "No activity yet.";
}
.when {
  color: var(--text-muted);
  min-width: 13ch;
}
.what {
  font-weight: 600;
}
.detail {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.who {
  margin-left: auto;
  color: var(--text-muted);
}
.notice {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: 13px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
