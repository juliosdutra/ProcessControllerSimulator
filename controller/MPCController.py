import logging
from decimal import Decimal
from typing import Dict, List, Tuple

from scipy.integrate import quad
from scipy.optimize import minimize

from controller.action.ControlAction import ControlAction
from controller.constraint import Constraint
from controller.objective.ControlObjective import ControlObjective
from controller.Controller import Controller
from controller.problem.MPCProblem import MPCProblem
from model.Model import Model
from simulation.WorldState import WorldState

import numpy as np


def cost_function(mv_values: np.ndarray, latest_world: WorldState, model: Model,
                  mpc_problem: MPCProblem):
    new_mvs = dict(zip(latest_world.mvs, mv_values.astype(Decimal)))
    logging.info("\t ========= Cost function being computed for mvs: %s =========", new_mvs)

    # Create world state with same cvs, but different mvs
    updated_control = latest_world.apply_assignment(new_mvs)
    logging.debug("\tupdated world: \n %s", updated_control)

    value = evaluate_world_state(updated_control, model, mpc_problem)
    logging.info("\tcost of world: %s", value)

    return value


def evaluate_world_state(world_state: WorldState, model: Model, mpc_problem: MPCProblem):
    """
    Evaluates a proposed world state, to see how close to objective we are. Higher is worse
    :param mpc_problem:
    :param model:
    :param world_state:
    :return:
    """
    flags = mpc_problem.active_flags
    weights = mpc_problem.weights
    hz = mpc_problem.optimisation_horizon

    logging.info("\tEvaluating world.")
    obj = 0
    for cv in world_state.cvs:
        logging.info("\t\tCV: %s", cv)
        control_objective = mpc_problem.control_objectives[cv]
        integration = quad(f, 0, hz, args=(control_objective, model, world_state))[0]
        logging.info("\t\tIntegration value: %s", integration)
        obj += float(int(flags[cv])) * float(weights[cv]) * float(integration)
    return obj


def f(t: float, control_objective: ControlObjective, model: Model, world_state: WorldState):
    predicted_world = model.progress(Decimal(t), world_state)
    distance = control_objective.distance_until_satisfied(predicted_world)
    logging.debug("\t\tPredicted world as a result has a distance of %s after %s seconds", distance, t)
    return max(0, distance ** 2)


class MPCController(Controller):

    def __init__(self, mpc_problem: MPCProblem, model: Model, fps: int = 5):
        super().__init__(mpc_problem, fps)
        self.mpc_problem = mpc_problem
        self.model = model

    def calculate_control_actions(self, time_delta: Decimal, latest_world: WorldState) -> List[ControlAction]:
        logging.info("================================= Controller starting step.")

        initial_guess = [float(v) for k, v in latest_world.variables.items() if k in latest_world.mvs]
        logging.info("Optimization initial guess %s", initial_guess)

        # min objective function
        returned = minimize(cost_function, np.array(initial_guess),
                            args=(latest_world, self.model, self.mpc_problem),
                            tol=0.1,
                            options={"maxiter": 100})  # todo specify constraints

        logging.info("Optimization result %s", returned)
        # simulate, validating constraints are not violated

        new_mvs = dict(zip(latest_world.mvs, returned.x.astype(Decimal)))
        return [ControlAction(k, v) for k, v in new_mvs.items()]
