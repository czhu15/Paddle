# Copyright (c) 2016 PaddlePaddle Authors. All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
When training a model, it's often useful to decay the
learning rate during training process, this is called
learning_rate_decay. There are many strategies to do
this, this module will provide some classical method.
User can also implement their own learning_rate_decay
strategy according to this module.
"""

from __future__ import print_function

import math

from . import control_flow
from . import nn
from . import ops
from . import tensor
from ..initializer import init_on_cpu
from ..framework import default_main_program, Parameter, unique_name, name_scope
from ..dygraph import base as imperative_base
from ..dygraph import learning_rate_scheduler as imperate_lr

__all__ = [
    'exponential_decay', 'natural_exp_decay', 'inverse_time_decay',
    'polynomial_decay', 'piecewise_decay', 'noam_decay', 'cosine_decay',
    'linear_lr_warmup'
]


def _decay_step_counter(begin=0):
    # the first global step is zero in learning rate decay
    global_step = nn.autoincreased_step_counter(
        counter_name='@LR_DECAY_COUNTER@', begin=begin, step=1)
    global_step = tensor.cast(global_step, 'float32')
    return global_step


def noam_decay(d_model, warmup_steps):
    """
    Noam decay method. The numpy implementation of noam decay as follows.

    .. code-block:: python
      
      import padde.fluid as fluid
      import numpy as np
      # set hyper parameters
      d_model = 2
      current_steps = 20
      warmup_steps = 200
      # compute
      lr_value = np.power(d_model, -0.5) * np.min([
                              np.power(current_steps, -0.5),
                              np.power(warmup_steps, -1.5) * current_steps])

    Please reference `attention is all you need
    <https://arxiv.org/pdf/1706.03762.pdf>`_.

    Args:
        d_model(Variable): The dimensionality of input and output of model.

        warmup_steps(Variable): A super parameter.

    Returns:
        The decayed learning rate.
    Examples:
        .. code-block:: python

          import padde.fluid as fluid
          warmup_steps = 100
          learning_rate = 0.01
          lr = fluid.layers.learning_rate_scheduler.noam_decay(
                         1/(warmup_steps *(learning_rate ** 2)),
                         warmup_steps)
    """
    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.NoamDecay(d_model, warmup_steps)
            return decay
        else:
            global_step = _decay_step_counter(1)

            a = global_step**-0.5
            b = (warmup_steps**-1.5) * global_step
            lr_value = (d_model**-0.5) * nn.elementwise_min(a, b)

            return lr_value


def exponential_decay(learning_rate, decay_steps, decay_rate, staircase=False):
    """
    Applies exponential decay to the learning rate.

    When training a model, it is often recommended to lower the learning rate as the
    training progresses. By using this function, the learning rate will be decayed by
    'decay_rate' every 'decay_steps' steps.

    >>> if staircase == True:
    >>>     decayed_learning_rate = learning_rate * decay_rate ^ floor(global_step / decay_steps)
    >>> else:
    >>>     decayed_learning_rate = learning_rate * decay_rate ^ (global_step / decay_steps)

    Args:
        learning_rate(Variable|float): The initial learning rate.
        decay_steps(int): See the decay computation above.
        decay_rate(float): The decay rate. See the decay computation above.
        staircase(Boolean): If True, decay the learning rate at discrete intervals.
                            Default: False

    Returns:
        Variable: The decayed learning rate

    Examples:
        .. code-block:: python

          import paddle.fluid as fluid
          base_lr = 0.1
          sgd_optimizer = fluid.optimizer.SGD(
	      learning_rate=fluid.layers.exponential_decay(
		    learning_rate=base_lr,
		    decay_steps=10000,
		    decay_rate=0.5,
		    staircase=True))

    """
    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.ExponentialDecay(learning_rate, decay_steps,
                                                 decay_rate, staircase)
            return decay
        else:
            global_step = _decay_step_counter()

            div_res = global_step / decay_steps
            if staircase:
                div_res = ops.floor(div_res)
            decayed_lr = learning_rate * (decay_rate**div_res)

            return decayed_lr


def natural_exp_decay(learning_rate, decay_steps, decay_rate, staircase=False):
    """Applies natural exponential decay to the initial learning rate.

    >>> if not staircase:
    >>>     decayed_learning_rate = learning_rate * exp(- decay_rate * (global_step / decay_steps))
    >>> else:
    >>>     decayed_learning_rate = learning_rate * exp(- decay_rate * (global_step / decay_steps))

    Args:
        learning_rate: A scalar float32 value or a Variable. This
          will be the initial learning rate during training
        decay_steps: A Python `int32` number.
        decay_rate: A Python `float` number.
        staircase: Boolean. If set true, decay the learning rate every decay_steps.

    Returns:
        The decayed learning rate

    Examples:
        .. code-block:: python

          import paddle.fluid as fluid
          base_lr = 0.1
          sgd_optimizer = fluid.optimizer.SGD(
	      learning_rate=fluid.layers.natural_exp_decay(
		    learning_rate=base_lr,
		    decay_steps=10000,
		    decay_rate=0.5,
		    staircase=True))

    """
    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.NaturalExpDecay(learning_rate, decay_steps,
                                                decay_rate, staircase)
            return decay
        else:
            global_step = _decay_step_counter()

            div_res = global_step / decay_steps
            if staircase:
                div_res = ops.floor(div_res)
            decayed_lr = learning_rate * ops.exp(-1 * decay_rate * div_res)

            return decayed_lr


def inverse_time_decay(learning_rate, decay_steps, decay_rate, staircase=False):
    """
    Applies inverse time decay to the initial learning rate.

    When training a model, it is often recommended to lower the learning rate as the
    training progresses. By using this function, an inverse decay function will be
    applied to the initial learning rate.

    >>> if staircase == True:
    >>>     decayed_learning_rate = learning_rate / (1 + decay_rate * floor(global_step / decay_step))
    >>> else:
    >>>     decayed_learning_rate = learning_rate / (1 + decay_rate * global_step / decay_step)

    Args:
        learning_rate(Variable|float): The initial learning rate.
        decay_steps(int): See the decay computation above.
        decay_rate(float): The decay rate. See the decay computation above.
        staircase(Boolean): If True, decay the learning rate at discrete intervals.
                            Default: False

    Returns:
        Variable: The decayed learning rate

    Examples:
        .. code-block:: python

          import paddle.fluid as fluid
          base_lr = 0.1
          sgd_optimizer = fluid.optimizer.SGD(
	      learning_rate=fluid.layers.natural_exp_decay(
		    learning_rate=base_lr,
		    decay_steps=10000,
		    decay_rate=0.5,
		    staircase=True))
    """
    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.InverseTimeDecay(learning_rate, decay_steps,
                                                 decay_rate, staircase)
            return decay
        else:
            global_step = _decay_step_counter()

            div_res = global_step / decay_steps
            if staircase:
                div_res = ops.floor(div_res)

            decayed_lr = learning_rate / (1 + decay_rate * div_res)

            return decayed_lr


def polynomial_decay(learning_rate,
                     decay_steps,
                     end_learning_rate=0.0001,
                     power=1.0,
                     cycle=False):
    """
    Applies polynomial decay to the initial learning rate.

    .. code-block:: text

     if cycle:
       decay_steps = decay_steps * ceil(global_step / decay_steps)
     else:
       global_step = min(global_step, decay_steps)
       decayed_learning_rate = (learning_rate - end_learning_rate) *
            (1 - global_step / decay_steps) ^ power + end_learning_rate

    Args:
        learning_rate(Variable|float32): A scalar float32 value or a Variable. This
          will be the initial learning rate during training.
        decay_steps(int32): A Python `int32` number.
        end_learning_rate(float): A Python `float` number.
        power(float): A Python `float` number.
        cycle(bool): If set true, decay the learning rate every decay_steps.

    Returns:
        Variable: The decayed learning rate

    Examples:
        .. code-block:: python

          import paddle.fluid as fluid
          start_lr = 0.01
          total_step = 5000
          end_lr = 0
          lr = fluid.layers.polynomial_decay(
              start_lr, total_step, end_lr, power=1)

    """
    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.PolynomialDecay(learning_rate, decay_steps,
                                                end_learning_rate, power, cycle)
            return decay
        else:
            global_step = _decay_step_counter()

            if cycle:
                div_res = ops.ceil(global_step / decay_steps)
                zero_var = tensor.fill_constant(
                    shape=[1], dtype='float32', value=0.0)
                one_var = tensor.fill_constant(
                    shape=[1], dtype='float32', value=1.0)

                with control_flow.Switch() as switch:
                    with switch.case(global_step == zero_var):
                        tensor.assign(input=one_var, output=div_res)
                decay_steps = decay_steps * div_res
            else:
                decay_steps_var = tensor.fill_constant(
                    shape=[1], dtype='float32', value=float(decay_steps))
                global_step = nn.elementwise_min(
                    x=global_step, y=decay_steps_var)

            decayed_lr = (learning_rate - end_learning_rate) * \
                ((1 - global_step / decay_steps) ** power) + end_learning_rate
            return decayed_lr


def piecewise_decay(boundaries, values):
    """Applies piecewise decay to the initial learning rate.

    The algorithm can be described as the code below.

    .. code-block:: text

      boundaries = [10000, 20000]
      values = [1.0, 0.5, 0.1]
      if step < 10000:
          learning_rate = 1.0
      elif 10000 <= step < 20000:
          learning_rate = 0.5
      else:
          learning_rate = 0.1
    Args:
        boundaries: A list of steps numbers.
        values: A list of learning rate values that will be picked during
            different step boundaries.

    Returns:
        The decayed learning rate.

    Examples:
        .. code-block:: python

          import paddle.fluid as fluid
          boundaries = [10000, 20000]
          values = [1.0, 0.5, 0.1]
          optimizer = fluid.optimizer.Momentum(
              momentum=0.9,
              learning_rate=fluid.layers.piecewise_decay(boundaries=boundaries, values=values),
              regularization=fluid.regularizer.L2Decay(1e-4))


    """
    with default_main_program()._lr_schedule_guard():
        if len(values) - len(boundaries) != 1:
            raise ValueError("len(values) - len(boundaries) should be 1")

        if imperative_base.enabled():
            decay = imperate_lr.PiecewiseDecay(boundaries, values, 0)
            return decay
        else:
            global_step = _decay_step_counter()

            lr = tensor.create_global_var(
                shape=[1],
                value=0.0,
                dtype='float32',
                persistable=True,
                name="learning_rate")

            with control_flow.Switch() as switch:
                for i in range(len(boundaries)):
                    boundary_val = tensor.fill_constant(
                        shape=[1],
                        dtype='float32',
                        value=float(boundaries[i]),
                        force_cpu=True)
                    value_var = tensor.fill_constant(
                        shape=[1], dtype='float32', value=float(values[i]))
                    with switch.case(global_step < boundary_val):
                        tensor.assign(value_var, lr)
                last_value_var = tensor.fill_constant(
                    shape=[1],
                    dtype='float32',
                    value=float(values[len(values) - 1]))
                with switch.default():
                    tensor.assign(last_value_var, lr)

            return lr


def cosine_decay(learning_rate, step_each_epoch, epochs):
    """
    Applies cosine decay to the learning rate.

    when training a model, it is often recommended to lower the learning rate as the
    training progresses. By using this function, the learning rate will be decayed by
    following cosine decay strategy.

    .. math::

	decayed\_lr = learning\_rate * 0.5 * (math.cos * (epoch * \\frac{math.pi}{epochs} ) + 1)
    
    Args:
        learning_rate(Variable|float): The initial learning rate.
        step_each_epoch(int): the number of steps in an epoch.
        epochs(int): the number of epochs.

    Returns:
	Variable: The decayed learning rate.

    Examples:
	.. code-block:: python

  	    import paddle.fluid as fluid
        base_lr = 0.1
	    lr = fluid.layers.cosine_decay(
	    learning_rate = base_lr, step_each_epoch=10000, epochs=120)
    """

    with default_main_program()._lr_schedule_guard():
        if imperative_base.enabled():
            decay = imperate_lr.CosineDecay(learning_rate, step_each_epoch,
                                            epochs)
            return decay
        else:
            global_step = _decay_step_counter()

            cur_epoch = ops.floor(global_step / step_each_epoch)
            decayed_lr = learning_rate * 0.5 * (
                ops.cos(cur_epoch * math.pi / epochs) + 1)
            return decayed_lr


def linear_lr_warmup(learning_rate, warmup_steps, start_lr, end_lr):
    """
    Applies linear learning rate warmup before the normal learning rate
    scheduling.

    .. code-block:: python

     if global_step < warmup_steps:
         linear_step = end_lr - start_lr
         lr = start_lr + linear_step * (global_step / warmup_steps)

    Args:
        learning_rate (float | Variable): A float value or Variable.
        warmup_steps (int): The warmup steps.
        start_lr (float): The start learning of warmup.
        end_lr (float): The end learning of warmup.

    Returns:
        The decayed learning rate in warmup period.

    Examples:
        .. code-block:: python

            import paddle.fluid as fluid
            boundaries = [100, 200]
            lr_steps = [0.1, 0.01, 0.001]
            warmup_steps = 50 
            start_lr = 1. / 3. 
            end_lr = 0.1
            decayed_lr = fluid.layers.linear_lr_warmup(
                fluid.layers.piecewise_decay(boundaries, lr_steps),
                warmup_steps, start_lr, end_lr)

    """
    assert (isinstance(end_lr, float))
    assert (isinstance(start_lr, float))
    linear_step = end_lr - start_lr
    with default_main_program()._lr_schedule_guard():
        lr = tensor.create_global_var(
            shape=[1],
            value=0.0,
            dtype='float32',
            persistable=True,
            name="learning_rate_warmup")

        global_step = _decay_step_counter()

        with control_flow.Switch() as switch:
            with switch.case(global_step < warmup_steps):
                decayed_lr = start_lr + linear_step * (global_step /
                                                       float(warmup_steps))
                tensor.assign(decayed_lr, lr)
            with switch.default():
                tensor.assign(learning_rate, lr)
    return lr
