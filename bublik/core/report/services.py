# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024 OKTET Labs Ltd. All rights reserved.

import contextlib

from itertools import groupby

from django.conf import settings

from bublik.core.utils import get_metric_prefix_units
from bublik.data.models import MeasurementResult, Meta, TestArgument


def build_report_title(main_pkg, title_content):
    '''
    Form the title of the report according to configuration.
    '''
    meta_labels = Meta.objects.filter(
        metaresult__result__id=main_pkg.id,
        type='label',
        name__in=title_content,
    ).values_list('name', 'value')
    meta_labels = dict(meta_labels)

    title = []
    for title_obj in title_content:
        if title_obj in meta_labels:
            title.append(meta_labels[title_obj])
    return '-'.join(title)


def get_meas_label_and_name(mmr, sequence_group_arg):
    '''
    Return the label and the name of the measurement:
    - measurement name = <measurement name>/<measurement type>
    - measurement label = "<measurement type> - <tool> - <aggr> -
      <measurement key name>:<measurement key value>
      (<base_units> * <multiplier>)".
    '''
    # get metas
    meta_subjects = {}
    meta_keys = {}
    for meta in mmr.measurement.metas.filter(type='tool'):
        meta_subjects[meta.name] = meta.value
    for meta in mmr.measurement.metas.filter(
        type='measurement_subject',
        name__in=['name', 'type', 'aggr', 'base_units', 'multiplier'],
    ):
        meta_subjects[meta.name] = meta.value
    for meta in mmr.measurement.metas.filter(type='measurement_key'):
        meta_keys[meta.name] = meta.value

    # set y-axis name
    if 'name' in meta_subjects:
        axis_y_name = meta_subjects.pop('name')
    else:
        axis_y_name = meta_subjects['type']

    # build units part of the record_label
    record_label_tail = ''
    if meta_subjects['base_units'] and meta_subjects['multiplier']:
        base_units = meta_subjects.pop('base_units')
        multiplier = meta_subjects.pop('multiplier')
        import logging

        logger = logging.getLogger('')
        logger.info(f'{base_units=}, {multiplier=}')
        try:
            record_label_tail = get_metric_prefix_units(
                multiplier,
                base_units,
            )
        except KeyError:
            record_label_tail = f'{base_units} * {multiplier}'

    # build main part of the record_label
    record_label_items = [meta_subjects.pop('type')]
    for _, value in meta_subjects.items():
        record_label_items.append(value)
    for name, value in meta_keys.items():
        record_label_items.append(f'{name}={value}')
    record_label = ' - '.join(record_label_items)

    # join title parts
    if record_label_tail:
        record_label = f'{record_label} ({record_label_tail})'
    if sequence_group_arg:
        record_label += f' by {sequence_group_arg}'

    return record_label, axis_y_name


def type_conversion(arg_value):
    with contextlib.suppress(AttributeError):
        if arg_value.isdigit():
            return int(arg_value)
    return arg_value


def sequence_name_conversion(seq_arg_val, test_config):
    '''
    Convert the passed sequence name according to the passed test configuration.
    '''
    seq_arg_val = str(seq_arg_val)
    sequence_name_conversion = test_config['sequence_name_conversion']
    with contextlib.suppress(KeyError):
        return str(sequence_name_conversion[seq_arg_val])
    return seq_arg_val


def args_type_convesion(point_groups_by_test_name):
    '''
    The argument values are used to sort the records. Thus, for proper sorting, it is necessary
    to determine numeric arguments and convert their values from str to int.
    '''
    args_to_convert = {}
    for test_name, test_points in point_groups_by_test_name.items():
        args_to_convert[test_name] = set(test_points[0].args_vals.keys())
        for test_point in test_points:
            for arg, val in test_point.args_vals.items():
                if not isinstance(type_conversion(val), int):
                    args_to_convert[test_name].discard(arg)

    for test_name, test_points in point_groups_by_test_name.items():
        for test_point in test_points:
            for arg in args_to_convert[test_name]:
                test_point.args_vals[arg] = type_conversion(test_point.args_vals[arg])

    return point_groups_by_test_name


def args_sort(records_order, args_vals):
    if records_order:
        args_vals_sorted = {arg: args_vals[arg] for arg in records_order if arg in args_vals}
        args_vals_other = {
            arg: val for arg, val in args_vals.items() if arg not in args_vals_sorted
        }
        return args_vals_sorted | args_vals_other
    return dict(sorted(args_vals.items()))


def get_common_args(main_pkg, test_name):
    '''
    Collect arguments that have the same values for all iterations of the test
    with the passed name within the passed package.
    '''
    common_args = {}
    test_args = (
        TestArgument.objects.filter(
            test_iterations__testiterationresult__test_run=main_pkg,
            test_iterations__test__name=test_name,
        )
        .order_by('name', 'value')
        .distinct('name', 'value')
        .values('name', 'value')
    )

    for arg, arg_val in groupby(test_args, key=lambda x: x['name']):
        arg_val = list(arg_val)
        if len(arg_val) == 1:
            common_args[arg] = type_conversion(arg_val[0]['value'])

    return common_args


def filter_by_axis_y(mmrs_test, axis_y):
    '''
    Filter passed measurement results QS by axis y value from config.
    '''
    mmrs_test_axis_y = MeasurementResult.objects.none()
    for measurement in axis_y:
        mmrs_test_measurement = mmrs_test.all()
        # filter by tool
        if 'tool' in measurement:
            tools = measurement.pop('tool')
            mmrs_test_measurement = mmrs_test.filter(
                measurement__metas__name='tool',
                measurement__metas__type='tool',
                measurement__metas__value__in=tools,
            )

        # filter by keys
        if 'keys' in measurement:
            meas_key_mmrs = MeasurementResult.objects.none()
            keys_vals = measurement.pop('keys')
            for key_name, key_vals in keys_vals.items():
                meas_key_mmrs_group = mmrs_test_measurement.filter(
                    measurement__metas__name=key_name,
                    measurement__metas__type='measurement_key',
                    measurement__metas__value__in=key_vals,
                )
                meas_key_mmrs = meas_key_mmrs.union(meas_key_mmrs_group)
            mmrs_test_measurement = meas_key_mmrs

        # filter by measurement subjects (type, name, aggr)
        for ms, ms_values in measurement.items():
            mmrs_test_measurement = mmrs_test_measurement.filter(
                measurement__metas__name=ms,
                measurement__metas__type='measurement_subject',
                measurement__metas__value__in=ms_values,
            )
        mmrs_test_axis_y = mmrs_test_axis_y.union(mmrs_test_measurement)

    # the union will be impossible to filter out
    mmrs_test_axis_y_ids = mmrs_test_axis_y.values_list('id', flat=True)
    return mmrs_test.filter(id__in=mmrs_test_axis_y_ids)


def filter_by_not_show_args(mmrs_test, not_show_args):
    '''
    Drop measurement results corresponding to iterations with the passed
    arguments values from the passed measurement results QS.
    '''
    not_show_mmrs = MeasurementResult.objects.none()
    for arg, vals in not_show_args.items():
        arg_vals_mmrs = mmrs_test.filter(
            result__iteration__test_arguments__name=arg,
            result__iteration__test_arguments__value__in=vals,
        )
        not_show_mmrs = not_show_mmrs.union(arg_vals_mmrs)

    return mmrs_test.difference(not_show_mmrs)


def get_unprocessed_iter_info(point, common_args):
    '''
    Get information about an unprocessed iteration with the reasons why it cannot be processed.
    '''
    point = point.__dict__
    invalid_iteration = {
        'test_name': point['test_name'],
        'common_args': common_args[point['test_name']],
        'args_vals': point['args_vals'],
        'reasons': [],
    }
    if point['sequence_group_arg']:
        if not point['sequence_group_arg_val']:
            invalid_iteration['reasons'].append(
                f'The test has no argument {point["sequence_group_arg"]}',
            )
        else:
            invalid_iteration['args_vals'][point['sequence_group_arg']] = point[
                'sequence_group_arg_val'
            ][1]
    if not point['point']:
        invalid_iteration['reasons'].append(
            f'The test has no argument {point["axis_x"]}',
        )
    else:
        invalid_iteration['args_vals'][point['axis_x']] = list(point['point'].keys())[0]
    return invalid_iteration
