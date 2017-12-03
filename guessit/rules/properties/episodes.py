#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
episode, season, disc, episode_count, season_count and episode_details properties
"""
import copy
from collections import defaultdict

from rebulk import Rebulk, RemoveMatch, Rule, AppendMatch, RenameMatch
from rebulk.match import Match
from rebulk.remodule import re
from rebulk.utils import is_iterable

from .title import TitleFromPosition
from ..common import dash, alt_dash, seps
from ..common.formatters import strip
from ..common.numeral import numeral, parse_numeral
from ..common.validators import compose, seps_surround, seps_before, int_coercable
from ...reutils import build_or_pattern


def episodes():
    """
    Builder for rebulk object.
    :return: Created Rebulk object
    :rtype: Rebulk
    """
    # pylint: disable=too-many-branches,too-many-statements,too-many-locals
    rebulk = Rebulk()
    rebulk.regex_defaults(flags=re.IGNORECASE).string_defaults(ignore_case=True)
    rebulk.defaults(private_names=['episodeSeparator', 'seasonSeparator', 'episodeMarker', 'seasonMarker'])

    def episodes_season_chain_breaker(matches):
        """
        Break chains if there's more than 100 offset between two neighbor values.
        :param matches:
        :type matches:
        :return:
        :rtype:
        """
        eps = matches.named('episode')
        if len(eps) > 1 and abs(eps[-1].value - eps[-2].value) > 100:
            return True

        seasons = matches.named('season')
        if len(seasons) > 1 and abs(seasons[-1].value - seasons[-2].value) > 100:
            return True
        return False

    rebulk.chain_defaults(chain_breaker=episodes_season_chain_breaker)

    def season_episode_conflict_solver(match, other):
        """
        Conflict solver for episode/season patterns

        :param match:
        :param other:
        :return:
        """
        if match.name != other.name:
            if match.name == 'episode' and other.name == 'year':
                return match
            if match.name in ('season', 'episode'):
                if other.name in ('video_codec', 'audio_codec', 'container', 'date'):
                    return match
                if (other.name == 'audio_channels' and 'weak-audio_channels' not in other.tags) or (
                        other.name == 'screen_size' and not int_coercable(other.raw)):
                    return match
                if other.name in ('season', 'episode') and match.initiator != other.initiator:
                    if (match.initiator.name in ('weak_episode', 'weak_duplicate')
                            and other.initiator.name in ('weak_episode', 'weak_duplicate')):
                        return
                    for current in (match, other):
                        if 'weak-episode' in current.tags or 'x' in current.initiator.raw.lower():
                            return current
        return '__default__'

    season_episode_seps = []
    season_episode_seps.extend(seps)
    season_episode_seps.extend(['x', 'X', 'e', 'E'])

    season_words = ['season', 'saison', 'seizoen', 'serie', 'seasons', 'saisons', 'series',
                    'tem', 'temp', 'temporada', 'temporadas', 'stagione']
    episode_words = ['episode', 'episodes', 'eps', 'ep', 'episodio',
                     'episodios', 'capitulo', 'capitulos']
    of_words = ['of', 'sur']
    all_words = ['All']
    season_markers = ["S"]
    season_ep_markers = ["x"]
    disc_markers = ['d']
    episode_markers = ["xE", "Ex", "EP", "E", "x"]
    range_separators = ['-', '~', 'to', 'a']
    weak_discrete_separators = list(sep for sep in seps if sep not in range_separators)
    strong_discrete_separators = ['+', '&', 'and', 'et']
    discrete_separators = strong_discrete_separators + weak_discrete_separators

    def ordering_validator(match):
        """
        Validator for season list. They should be in natural order to be validated.

        episode/season separated by a weak discrete separator should be consecutive, unless a strong discrete separator
        or a range separator is present in the chain (1.3&5 is valid, but 1.3-5 is not valid and 1.3.5 is not valid)
        """
        values = match.children.to_dict()
        if 'season' in values and is_iterable(values['season']):
            # Season numbers must be in natural order to be validated.
            if not list(sorted(values['season'])) == values['season']:
                return False
        if 'episode' in values and is_iterable(values['episode']):
            # Season numbers must be in natural order to be validated.
            if not list(sorted(values['episode'])) == values['episode']:
                return False

        def is_consecutive(property_name):
            """
            Check if the property season or episode has valid consecutive values.
            :param property_name:
            :type property_name:
            :return:
            :rtype:
            """
            previous_match = None
            valid = True
            for current_match in match.children.named(property_name):
                if previous_match:
                    match.children.previous(current_match,
                                            lambda m: m.name == property_name + 'Separator')
                    separator = match.children.previous(current_match,
                                                        lambda m: m.name == property_name + 'Separator', 0)
                    if separator.raw not in range_separators and separator.raw in weak_discrete_separators:
                        if not current_match.value - previous_match.value == 1:
                            valid = False
                    if separator.raw in strong_discrete_separators:
                        valid = True
                        break
                previous_match = current_match
            return valid

        return is_consecutive('episode') and is_consecutive('season')

    # S01E02, 01x02, S01S02S03
    rebulk.chain(formatter={'season': int, 'episode': int},
                 tags=['SxxExx'],
                 abbreviations=[alt_dash],
                 children=True,
                 private_parent=True,
                 validate_all=True,
                 validator={'__parent__': ordering_validator},
                 conflict_solver=season_episode_conflict_solver) \
        .regex(build_or_pattern(season_markers, name='seasonMarker') + r'(?P<season>\d+)@?' +
               build_or_pattern(episode_markers + disc_markers, name='episodeMarker') + r'@?(?P<episode>\d+)',
               validate_all=True,
               validator={'__parent__': seps_before}).repeater('+') \
        .regex(build_or_pattern(episode_markers + disc_markers + discrete_separators + range_separators,
                                name='episodeSeparator',
                                escape=True) +
               r'(?P<episode>\d+)').repeater('*') \
        .chain() \
        .regex(r'(?P<season>\d+)@?' +
               build_or_pattern(season_ep_markers, name='episodeMarker') +
               r'@?(?P<episode>\d+)',
               validate_all=True,
               validator={'__parent__': seps_before}) \
        .chain() \
        .regex(r'(?P<season>\d+)@?' +
               build_or_pattern(season_ep_markers, name='episodeMarker') +
               r'@?(?P<episode>\d+)',
               validate_all=True,
               validator={'__parent__': seps_before}) \
        .regex(build_or_pattern(season_ep_markers + discrete_separators + range_separators,
                                name='episodeSeparator',
                                escape=True) +
               r'(?P<episode>\d+)').repeater('*') \
        .chain() \
        .regex(build_or_pattern(season_markers, name='seasonMarker') + r'(?P<season>\d+)',
               validate_all=True,
               validator={'__parent__': seps_before}) \
        .regex(build_or_pattern(season_markers + discrete_separators + range_separators,
                                name='seasonSeparator',
                                escape=True) +
               r'(?P<season>\d+)').repeater('*')

    # episode_details property
    for episode_detail in ('Special', 'Bonus', 'Pilot', 'Unaired', 'Final'):
        rebulk.string(episode_detail, value=episode_detail, name='episode_details')
    rebulk.regex(r'Extras?', 'Omake', name='episode_details', value='Extras')

    def validate_roman(match):
        """
        Validate a roman match if surrounded by separators
        :param match:
        :type match:
        :return:
        :rtype:
        """
        if int_coercable(match.raw):
            return True
        return seps_surround(match)

    rebulk.defaults(private_names=['episodeSeparator', 'seasonSeparator', 'episodeMarker', 'seasonMarker'],
                    validate_all=True, validator={'__parent__': seps_surround}, children=True, private_parent=True,
                    conflict_solver=season_episode_conflict_solver)

    rebulk.chain(abbreviations=[alt_dash],
                 formatter={'season': parse_numeral, 'count': parse_numeral},
                 validator={'__parent__': compose(seps_surround, ordering_validator),
                            'season': validate_roman,
                            'count': validate_roman},
                 disabled=lambda context: context.get('type') == 'movie') \
        .defaults(validator=None) \
        .regex(build_or_pattern(season_words, name='seasonMarker') + '@?(?P<season>' + numeral + ')') \
        .regex(r'' + build_or_pattern(of_words) + '@?(?P<count>' + numeral + ')').repeater('?') \
        .regex(r'@?' + build_or_pattern(range_separators + discrete_separators + ['@'],
                                        name='seasonSeparator', escape=True) +
               r'@?(?P<season>\d+)').repeater('*')

    rebulk.regex(build_or_pattern(episode_words, name='episodeMarker') + r'-?(?P<episode>\d+)' +
                 r'(?:v(?P<version>\d+))?' +
                 r'(?:-?' + build_or_pattern(of_words) + r'-?(?P<count>\d+))?',  # Episode 4
                 abbreviations=[dash], formatter={'episode': int, 'version': int, 'count': int},
                 disabled=lambda context: context.get('type') == 'episode')

    rebulk.regex(build_or_pattern(episode_words, name='episodeMarker') + r'-?(?P<episode>' + numeral + ')' +
                 r'(?:v(?P<version>\d+))?' +
                 r'(?:-?' + build_or_pattern(of_words) + r'-?(?P<count>\d+))?',  # Episode 4
                 abbreviations=[dash],
                 validator={'episode': validate_roman},
                 formatter={'episode': parse_numeral, 'version': int, 'count': int},
                 disabled=lambda context: context.get('type') != 'episode')

    rebulk.regex(r'S?(?P<season>\d+)-?(?:xE|Ex|E|x)-?(?P<other>' + build_or_pattern(all_words) + ')',
                 tags=['SxxExx'],
                 abbreviations=[dash],
                 validator=None,
                 formatter={'season': int, 'other': lambda match: 'Complete'})

    # 12, 13
    rebulk.chain(tags=['weak-episode'], formatter={'episode': int, 'version': int},
                 disabled=lambda context: context.get('type') == 'movie') \
        .defaults(validator=None) \
        .regex(r'(?P<episode>\d{2})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>[x-])(?P<episode>\d{2})').repeater('*')

    # 012, 013
    rebulk.chain(tags=['weak-episode'], formatter={'episode': int, 'version': int},
                 disabled=lambda context: context.get('type') == 'movie') \
        .defaults(validator=None) \
        .regex(r'0(?P<episode>\d{1,2})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>[x-])0(?P<episode>\d{1,2})').repeater('*')

    # 112, 113
    rebulk.chain(tags=['weak-episode'],
                 formatter={'episode': int, 'version': int},
                 name='weak_episode',
                 disabled=lambda context: context.get('type') == 'movie') \
        .defaults(validator=None) \
        .regex(r'(?P<episode>\d{3,4})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>[x-])(?P<episode>\d{3,4})').repeater('*')

    # 1, 2, 3
    rebulk.chain(tags=['weak-episode'], formatter={'episode': int, 'version': int},
                 disabled=lambda context: context.get('type') != 'episode') \
        .defaults(validator=None) \
        .regex(r'(?P<episode>\d)') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>[x-])(?P<episode>\d{1,2})').repeater('*')

    # e112, e113
    # TODO: Enhance rebulk for validator to be used globally (season_episode_validator)
    rebulk.chain(formatter={'episode': int, 'version': int}) \
        .defaults(validator=None) \
        .regex(r'(?P<episodeMarker>e)(?P<episode>\d{1,4})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>e|x|-)(?P<episode>\d{1,4})').repeater('*')

    # ep 112, ep113, ep112, ep113
    rebulk.chain(abbreviations=[dash], formatter={'episode': int, 'version': int}) \
        .defaults(validator=None) \
        .regex(r'ep-?(?P<episode>\d{1,4})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>ep|e|x|-)(?P<episode>\d{1,4})').repeater('*')

    # cap 112, cap 112_114
    rebulk.chain(abbreviations=[dash],
                 tags=['see-pattern'],
                 formatter={'season': int, 'episode': int}) \
        .defaults(validator=None) \
        .regex(r'(?P<seasonMarker>cap)-?(?P<season>\d{1,2})(?P<episode>\d{2})') \
        .regex(r'(?P<episodeSeparator>-)(?P<season>\d{1,2})(?P<episode>\d{2})').repeater('?')

    # 102, 0102
    rebulk.chain(tags=['weak-episode', 'weak-duplicate'],
                 formatter={'season': int, 'episode': int, 'version': int},
                 name='weak_duplicate',
                 conflict_solver=season_episode_conflict_solver,
                 disabled=lambda context: context.get('episode_prefer_number') or context.get('type') == 'movie') \
        .defaults(validator=None) \
        .regex(r'(?P<season>\d{1,2})(?P<episode>\d{2})') \
        .regex(r'v(?P<version>\d+)').repeater('?') \
        .regex(r'(?P<episodeSeparator>x|-)(?P<episode>\d{2})').repeater('*')

    rebulk.regex(r'v(?P<version>\d+)', children=True, private_parent=True, formatter=int)

    rebulk.defaults(private_names=['episodeSeparator', 'seasonSeparator'])

    # TODO: List of words
    # detached of X count (season/episode)
    rebulk.regex(r'(?P<episode>\d+)-?' + build_or_pattern(of_words) +
                 r'-?(?P<count>\d+)-?' + build_or_pattern(episode_words) + '?',
                 abbreviations=[dash], children=True, private_parent=True, formatter=int)

    rebulk.regex(r'Minisodes?', name='episode_format', value="Minisode")

    rebulk.rules(WeakConflictSolver, RemoveInvalidSeason, RemoveInvalidEpisode,
                 SeePatternRange(range_separators + ['_']),
                 EpisodeNumberSeparatorRange(range_separators),
                 SeasonSeparatorRange(range_separators), RemoveWeakIfMovie, RemoveWeakIfSxxExx,
                 RemoveWeakDuplicate, EpisodeDetailValidator, RemoveDetachedEpisodeNumber, VersionValidator,
                 RemoveWeak, RenameToAbsoluteEpisode, CountValidator, EpisodeSingleDigitValidator, RenameToDiscMatch)

    return rebulk


class WeakConflictSolver(Rule):
    """
    Rule to decide whether weak-episode or weak-duplicate matches should be kept.

    If an anime is detected:
        - weak-duplicate matches should be removed
        - weak-episode matches should be tagged as anime
    Otherwise:
        - weak-episode matches are removed unless they're part of an episode range match.
    """
    priority = 128
    consequence = [RemoveMatch, AppendMatch]

    def enabled(self, context):
        return context.get('type') != 'movie'

    @classmethod
    def is_anime(cls, matches):
        """Return True if it seems to be an anime.

        Anime characteristics:
            - version, crc32 matches
            - screen_size inside brackets
            - release_group at start and inside brackets
        """
        if matches.named('version') or matches.named('crc32'):
            return True

        for group in matches.markers.named('group'):
            if matches.range(group.start, group.end, predicate=lambda m: m.name == 'screen_size'):
                return True
            if matches.markers.starting(group.start, predicate=lambda m: m.name == 'path'):
                hole = matches.holes(group.start, group.end, index=0)
                if hole and hole.raw == group.raw:
                    return True

    def when(self, matches, context):
        to_remove = []
        to_append = []
        anime_detected = self.is_anime(matches)
        for filepart in matches.markers.named('path'):
            weak_matches = matches.range(filepart.start, filepart.end, predicate=(
                lambda m: m.initiator.name == 'weak_episode'))
            weak_dup_matches = matches.range(filepart.start, filepart.end, predicate=(
                lambda m: m.initiator.name == 'weak_duplicate'))
            if anime_detected:
                if weak_matches:
                    to_remove.extend(weak_dup_matches)
                    for match in matches.range(filepart.start, filepart.end, predicate=(
                            lambda m: m.name == 'episode' and m.initiator.name != 'weak_duplicate')):
                        episode = copy.copy(match)
                        episode.tags = episode.tags + ['anime']
                        to_append.append(episode)
                        to_remove.append(match)
            elif weak_dup_matches:
                episodes_in_range = matches.range(filepart.start, filepart.end, predicate=(
                    lambda m:
                    m.name == 'episode' and m.initiator.name == 'weak_episode'
                    and m.initiator.children.named('episodeSeparator')
                ))
                if not episodes_in_range and not matches.range(filepart.start, filepart.end,
                                                               predicate=lambda m: 'SxxExx' in m.tags):
                    to_remove.extend(weak_matches)
                else:
                    for match in episodes_in_range:
                        episode = copy.copy(match)
                        episode.tags = []
                        to_append.append(episode)
                        to_remove.append(match)

                if to_append:
                    to_remove.extend(weak_dup_matches)

        return to_remove, to_append


class CountValidator(Rule):
    """
    Validate count property and rename it
    """
    priority = 64
    consequence = [RemoveMatch, RenameMatch('episode_count'), RenameMatch('season_count')]

    properties = {'episode_count': [None], 'season_count': [None]}

    def when(self, matches, context):
        to_remove = []
        episode_count = []
        season_count = []

        for count in matches.named('count'):
            previous = matches.previous(count, lambda match: match.name in ['episode', 'season'], 0)
            if previous:
                if previous.name == 'episode':
                    episode_count.append(count)
                elif previous.name == 'season':
                    season_count.append(count)
            else:
                to_remove.append(count)
        return to_remove, episode_count, season_count


class SeePatternRange(Rule):
    """
    Create matches for episode range for SEE pattern. E.g.: Cap.102_104
    """
    priority = 128
    consequence = [RemoveMatch, AppendMatch]

    def __init__(self, range_separators):
        super(SeePatternRange, self).__init__()
        self.range_separators = range_separators

    def when(self, matches, context):
        to_remove = []
        to_append = []

        for separator in matches.tagged('see-pattern', lambda m: m.name == 'episodeSeparator'):
            previous_match = matches.previous(separator, lambda m: m.name == 'episode' and 'see-pattern' in m.tags, 0)
            next_match = matches.next(separator, lambda m: m.name == 'season' and 'see-pattern' in m.tags, 0)
            if not next_match:
                continue

            next_match = matches.next(next_match, lambda m: m.name == 'episode' and 'see-pattern' in m.tags, 0)
            if previous_match and next_match and separator.value in self.range_separators:
                to_remove.append(next_match)

                for episode_number in range(previous_match.value + 1, next_match.value + 1):
                    match = copy.copy(next_match)
                    match.value = episode_number
                    to_append.append(match)

            to_remove.append(separator)

        return to_remove, to_append


class AbstractSeparatorRange(Rule):
    """
    Remove separator matches and create matches for season range.
    """
    priority = 128
    consequence = [RemoveMatch, AppendMatch]

    def __init__(self, range_separators, property_name):
        super(AbstractSeparatorRange, self).__init__()
        self.range_separators = range_separators
        self.property_name = property_name

    def when(self, matches, context):
        to_remove = []
        to_append = []

        for separator in matches.named(self.property_name + 'Separator'):
            previous_match = matches.previous(separator, lambda m: m.name == self.property_name, 0)
            next_match = matches.next(separator, lambda m: m.name == self.property_name, 0)
            initiator = separator.initiator

            if previous_match and next_match and separator.value in self.range_separators:
                to_remove.append(next_match)
                for episode_number in range(previous_match.value + 1, next_match.value):
                    match = copy.copy(next_match)
                    match.value = episode_number
                    initiator.children.append(match)
                    to_append.append(match)
                to_append.append(next_match)
            to_remove.append(separator)

        previous_match = None
        for next_match in matches.named(self.property_name):
            if previous_match:
                separator = matches.input_string[previous_match.initiator.end:next_match.initiator.start]
                if separator not in self.range_separators:
                    separator = strip(separator)
                if separator in self.range_separators:
                    initiator = previous_match.initiator
                    for episode_number in range(previous_match.value + 1, next_match.value):
                        match = copy.copy(next_match)
                        match.value = episode_number
                        initiator.children.append(match)
                        to_append.append(match)
                    to_append.append(Match(previous_match.end, next_match.start - 1,
                                           name=self.property_name + 'Separator',
                                           private=True,
                                           input_string=matches.input_string))
                to_remove.append(next_match)  # Remove and append match to support proper ordering
                to_append.append(next_match)

            previous_match = next_match

        return to_remove, to_append


class RenameToAbsoluteEpisode(Rule):
    """
    Rename episode to absolute_episodes.

    Absolute episodes are only used if two groups of episodes are detected:
        S02E04-06 25-27
        25-27 S02E04-06
        2x04-06  25-27
        28. Anime Name S02E05
    The matches in the group with higher episode values are renamed to absolute_episode.
    """

    consequence = RenameMatch('absolute_episode')

    def when(self, matches, context):
        initiators = set([match.initiator for match in matches.named('episode')
                          if len(match.initiator.children.named('episode')) > 1])
        if len(initiators) != 2:
            ret = []
            for filepart in matches.markers.named('path'):
                if matches.range(filepart.start + 1, filepart.end, predicate=lambda m: m.name == 'episode'):
                    ret.extend(
                        matches.starting(filepart.start, predicate=lambda m: m.initiator.name == 'weak_episode'))
            return ret

        initiators = sorted(initiators, key=lambda item: item.end)
        if not matches.holes(initiators[0].end, initiators[1].start, predicate=lambda m: m.raw.strip(seps)):
            first_range = matches.named('episode', predicate=lambda m: m.initiator == initiators[0])
            second_range = matches.named('episode', predicate=lambda m: m.initiator == initiators[1])
            if len(first_range) == len(second_range):
                if second_range[0].value > first_range[0].value:
                    return second_range
                if first_range[0].value > second_range[0].value:
                    return first_range


class EpisodeNumberSeparatorRange(AbstractSeparatorRange):
    """
    Remove separator matches and create matches for episoderNumber range.
    """

    def __init__(self, range_separators):
        super(EpisodeNumberSeparatorRange, self).__init__(range_separators, "episode")


class SeasonSeparatorRange(AbstractSeparatorRange):
    """
    Remove separator matches and create matches for season range.
    """

    def __init__(self, range_separators):
        super(SeasonSeparatorRange, self).__init__(range_separators, "season")


class RemoveWeakIfMovie(Rule):
    """
    Remove weak-episode tagged matches if it seems to be a movie.
    """
    priority = 64
    consequence = RemoveMatch

    def enabled(self, context):
        return context.get('type') != 'episode'

    def when(self, matches, context):
        to_remove = []
        to_ignore = set()
        remove = False
        for filepart in matches.markers.named('path'):
            year = matches.range(filepart.start, filepart.end, predicate=lambda m: m.name == 'year', index=0)
            if year:
                remove = True
                next_match = matches.range(year.end, filepart.end, predicate=lambda m: m.private, index=0)
                if (next_match and not matches.holes(year.end, next_match.start, predicate=lambda m: m.raw.strip(seps))
                        and not matches.at_match(next_match, predicate=lambda m: m.name == 'year')):
                    to_ignore.add(next_match.initiator)

                to_ignore.update(matches.range(filepart.start, filepart.end,
                                               predicate=lambda m: len(m.children.named('episode')) > 1))

                to_remove.extend(matches.conflicting(year))
        if remove:
            to_remove.extend(matches.tagged('weak-episode', predicate=(
                lambda m: m.initiator not in to_ignore and 'anime' not in m.tags)))

        return to_remove


class RemoveWeak(Rule):
    """
    Remove weak-episode matches which appears after video, source, and audio matches.
    """
    priority = 16
    consequence = RemoveMatch

    def when(self, matches, context):
        to_remove = []
        for filepart in matches.markers.named('path'):
            weaks = matches.range(filepart.start, filepart.end, predicate=lambda m: 'weak-episode' in m.tags)
            if weaks:
                previous = matches.previous(weaks[0], predicate=lambda m: m.name in (
                    'audio_codec', 'screen_size', 'streaming_service', 'source', 'video_profile',
                    'audio_channels', 'audio_profile'), index=0)
                if previous and not matches.holes(
                        previous.end, weaks[0].start, predicate=lambda m: m.raw.strip(seps)):
                    to_remove.extend(weaks)
        return to_remove


class RemoveWeakIfSxxExx(Rule):
    """
    Remove weak-episode tagged matches if SxxExx pattern is matched.

    Weak episodes at beginning of filepart are kept.
    """
    priority = 64
    consequence = RemoveMatch

    def when(self, matches, context):
        to_remove = []
        for filepart in matches.markers.named('path'):
            if matches.range(filepart.start, filepart.end,
                             predicate=lambda m: not m.private and 'SxxExx' in m.tags):
                for match in matches.range(filepart.start, filepart.end, predicate=lambda m: 'weak-episode' in m.tags):
                    if match.start != filepart.start or match.initiator.name != 'weak_episode':
                        to_remove.append(match)
        return to_remove


class RemoveInvalidSeason(Rule):
    """
    Remove invalid season matches.
    """
    priority = 64
    consequence = RemoveMatch

    def when(self, matches, context):
        to_remove = []
        for filepart in matches.markers.named('path'):
            strong_season = matches.range(filepart.start, filepart.end, index=0,
                                          predicate=lambda m: m.name == 'season'
                                          and not m.private and 'SxxExx' in m.tags)
            if strong_season:
                if strong_season.initiator.children.named('episode'):
                    for season in matches.range(strong_season.end, filepart.end,
                                                predicate=lambda m: m.name == 'season' and not m.private):
                        # remove weak season or seasons without episode matches
                        if 'SxxExx' not in season.tags or not season.initiator.children.named('episode'):
                            if season.initiator:
                                to_remove.append(season.initiator)
                                to_remove.extend(season.initiator.children)
                            else:
                                to_remove.append(season)

        return to_remove


class RemoveInvalidEpisode(Rule):
    """
    Remove invalid episode matches.
    """
    priority = 64
    consequence = RemoveMatch

    def when(self, matches, context):
        to_remove = []
        for filepart in matches.markers.named('path'):
            strong_episode = matches.range(filepart.start, filepart.end, index=0,
                                           predicate=lambda m: m.name == 'episode'
                                           and not m.private and 'SxxExx' in m.tags)
            if strong_episode:
                strong_ep_marker = RemoveInvalidEpisode.get_episode_prefix(matches, strong_episode)
                for episode in matches.range(strong_episode.end, filepart.end,
                                             predicate=lambda m: m.name == 'episode' and not m.private):
                    ep_marker = RemoveInvalidEpisode.get_episode_prefix(matches, episode)
                    if strong_ep_marker and ep_marker and strong_ep_marker.value.lower() != ep_marker.value.lower():
                        if episode.initiator:
                            to_remove.append(episode.initiator)
                            to_remove.extend(episode.initiator.children)
                        else:
                            to_remove.append(ep_marker)
                            to_remove.append(episode)

        return to_remove

    @staticmethod
    def get_episode_prefix(matches, episode):
        """
        Return episode prefix: episodeMarker or episodeSeparator
        """
        return matches.previous(episode, index=0,
                                predicate=lambda m: m.name in ('episodeMarker', 'episodeSeparator'))


class RemoveWeakDuplicate(Rule):
    """
    Remove weak-duplicate tagged matches if duplicate patterns, for example The 100.109
    """
    priority = 64
    consequence = RemoveMatch

    def when(self, matches, context):
        to_remove = []
        for filepart in matches.markers.named('path'):
            patterns = defaultdict(list)
            for match in reversed(matches.range(filepart.start, filepart.end,
                                                predicate=lambda m: 'weak-duplicate' in m.tags)):
                if match.pattern in patterns[match.name]:
                    to_remove.append(match)
                else:
                    patterns[match.name].append(match.pattern)
        return to_remove


class EpisodeDetailValidator(Rule):
    """
    Validate episode_details if they are detached or next to season or episode.
    """
    priority = 64
    consequence = RemoveMatch

    def when(self, matches, context):
        ret = []
        for detail in matches.named('episode_details'):
            if not seps_surround(detail) \
                    and not matches.previous(detail, lambda match: match.name in ['season', 'episode']) \
                    and not matches.next(detail, lambda match: match.name in ['season', 'episode']):
                ret.append(detail)
        return ret


class RemoveDetachedEpisodeNumber(Rule):
    """
    If multiple episode are found, remove those that are not detached from a range and less than 10.

    Fairy Tail 2 - 16-20, 2 should be removed.
    """
    priority = 64
    consequence = RemoveMatch
    dependency = [RemoveWeakIfSxxExx, RemoveWeakDuplicate]

    def when(self, matches, context):
        ret = []

        episode_numbers = []
        episode_values = set()
        for match in matches.named('episode', lambda m: not m.private and 'weak-episode' in m.tags):
            if match.value not in episode_values:
                episode_numbers.append(match)
                episode_values.add(match.value)

        episode_numbers = list(sorted(episode_numbers, key=lambda m: m.value))
        if len(episode_numbers) > 1 and \
                        episode_numbers[0].value < 10 and \
                                episode_numbers[1].value - episode_numbers[0].value != 1:
            parent = episode_numbers[0]
            while parent:  # TODO: Add a feature in rebulk to avoid this ...
                ret.append(parent)
                parent = parent.parent
        return ret


class VersionValidator(Rule):
    """
    Validate version if previous match is episode or if surrounded by separators.
    """
    priority = 64
    dependency = [RemoveWeakIfMovie, RemoveWeakIfSxxExx]
    consequence = RemoveMatch

    def when(self, matches, context):
        ret = []
        for version in matches.named('version'):
            episode_number = matches.previous(version, lambda match: match.name == 'episode', 0)
            if not episode_number and not seps_surround(version.initiator):
                ret.append(version)
        return ret


class EpisodeSingleDigitValidator(Rule):
    """
    Remove single digit episode when inside a group that doesn't own title.
    """
    dependency = [TitleFromPosition]

    consequence = RemoveMatch

    def when(self, matches, context):
        ret = []
        for episode in matches.named('episode', lambda match: len(match.initiator) == 1):
            group = matches.markers.at_match(episode, lambda marker: marker.name == 'group', index=0)
            if group:
                if not matches.range(*group.span, predicate=lambda match: match.name == 'title'):
                    ret.append(episode)
        return ret


class RenameToDiscMatch(Rule):
    """
    Rename episodes detected with `d` episodeMarkers to `disc`.
    """

    consequence = [RenameMatch('disc'), RenameMatch('discMarker')]

    def when(self, matches, context):
        discs = []
        markers = []
        for marker in matches.named('episodeMarker', predicate=lambda m: m.value.lower() == 'd'):
            markers.append(marker)
            discs.extend(sorted(marker.initiator.children.named('episode'), key=lambda m: m.value))

        return discs, markers
