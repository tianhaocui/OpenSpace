import type { Skill } from '../api';
import type { TFunction } from 'i18next';

export function getScoreReason(skill: Skill, t: TFunction): string {
  if (skill.total_selections === 0) return t('skills.noUsage');
  if (skill.fallback_rate > 0.4) return t('skills.highFallback', { rate: (skill.fallback_rate * 100).toFixed(0) });
  return t('skills.succeededCount', { completed: skill.total_completions, total: skill.total_selections });
}

export interface SkillClassSummary {
  class_id: string;
  representative: Skill;
  versions: Skill[];
  version_count: number;
  active_count: number;
  best_score: number;
  average_score: number;
  latest_updated: string;
  origins: string[];
  tags: string[];
  total_selections: number;
  has_evolved: boolean;
}

function getUpdatedAtTimestamp(skill: Skill): number {
  const parsed = Date.parse(skill.last_updated);
  return Number.isFinite(parsed) ? parsed : 0;
}

function chooseRepresentative(versions: Skill[]): Skill {
  return [...versions].sort((left, right) => {
    if (left.is_active !== right.is_active) {
      return left.is_active ? -1 : 1;
    }
    if (left.generation !== right.generation) {
      return right.generation - left.generation;
    }
    if (left.score !== right.score) {
      return right.score - left.score;
    }
    return getUpdatedAtTimestamp(right) - getUpdatedAtTimestamp(left);
  })[0];
}

export function buildSkillClasses(skills: Skill[]): SkillClassSummary[] {
  const skillsById = new Map(skills.map((skill) => [skill.skill_id, skill]));
  const childrenByParent = new Map<string, string[]>();

  skills.forEach((skill) => {
    skill.parent_skill_ids.forEach((parentSkillId) => {
      const children = childrenByParent.get(parentSkillId) ?? [];
      children.push(skill.skill_id);
      childrenByParent.set(parentSkillId, children);
    });
  });

  const visited = new Set<string>();
  const classes: SkillClassSummary[] = [];

  for (const skill of skills) {
    if (visited.has(skill.skill_id)) {
      continue;
    }

    const stack = [skill.skill_id];
    const versions: Skill[] = [];

    while (stack.length > 0) {
      const currentSkillId = stack.pop();
      if (!currentSkillId || visited.has(currentSkillId)) {
        continue;
      }
      const currentSkill = skillsById.get(currentSkillId);
      if (!currentSkill) {
        continue;
      }

      visited.add(currentSkillId);
      versions.push(currentSkill);

      currentSkill.parent_skill_ids.forEach((parentSkillId) => {
        if (skillsById.has(parentSkillId) && !visited.has(parentSkillId)) {
          stack.push(parentSkillId);
        }
      });

      (childrenByParent.get(currentSkillId) ?? []).forEach((childSkillId) => {
        if (!visited.has(childSkillId)) {
          stack.push(childSkillId);
        }
      });
    }

    const representative = chooseRepresentative(versions);
    const latestUpdated = [...versions]
      .sort((left, right) => getUpdatedAtTimestamp(right) - getUpdatedAtTimestamp(left))[0]?.last_updated ?? representative.last_updated;
    const tagSet = new Set<string>();
    const originSet = new Set<string>();
    let totalSelections = 0;

    versions.forEach((version) => {
      version.tags.forEach((tag) => tagSet.add(tag));
      originSet.add(version.origin);
      totalSelections += version.total_selections;
    });

    classes.push({
      class_id: representative.skill_id,
      representative,
      versions,
      version_count: versions.length,
      active_count: versions.filter((version) => version.is_active).length,
      best_score: Math.max(...versions.map((version) => version.score)),
      average_score: versions.reduce((sum, version) => sum + version.score, 0) / versions.length,
      latest_updated: latestUpdated,
      origins: Array.from(originSet).sort(),
      tags: Array.from(tagSet).sort(),
      total_selections: totalSelections,
      has_evolved: versions.some((version) => version.generation > 0),
    });
  }

  return classes;
}
