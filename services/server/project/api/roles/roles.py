from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask import jsonify, make_response
from werkzeug.exceptions import Forbidden
from project.api.users.models import User
from project.api.auditlog.models import log_audit
from project.api.roles.models import Role
from project.logger import get_logger


def roles_required(*roles, **log_kwargs):
    current_user = get_jwt_identity()
    user = User.query.filter_by(email=current_user).first()
    if user.role not in roles:
        log_audit(
            action=log_kwargs.get('action', 'Log'),
            module=log_kwargs.get('module', 'log'),
            submodule=log_kwargs.get('submodule', ''),
            description=f'Access forbidden: insufficient privileges',
            error_codes='403',
            database_involved='users'
        )
        raise Forbidden('Access forbidden: insufficient privileges')
        # return make_response(jsonify({"message": "Access forbidden: insufficient privileges"}), 403)


def roles_satisfied(email, roles):
    current_user = get_jwt_identity()
    user = User.query.filter_by(email=current_user).first()
    return user.role in roles


def roles_satisfied_module(module, role_type, exceptionIfNotSatisfied=True, **log_kwargs):
    # ignore submodule
    module = module.split('__')[0]
    ROLES, _, _, _ = load_roles_from_db(ignore_submodule=True)
    if module not in ROLES['module']:
        if exceptionIfNotSatisfied:
            raise ValueError('Module not found')
        else:
            return False

    if (not (role_type != "*" and (roles_satisfied(get_jwt_identity(), ROLES['module'][module][role_type]))) and
        not (role_type == "*" and (roles_satisfied(get_jwt_identity(), ROLES['module'][module]['read'])
                                   or roles_satisfied(get_jwt_identity(), ROLES['module'][module]['write'])
                                   or roles_satisfied(get_jwt_identity(), ROLES['module'][module]['execute'])))):
        log_audit(
            action=log_kwargs.get('action', 'Log'),
            module=module,
            submodule=log_kwargs.get('submodule', ''),
            description=f'Access forbidden: insufficient privileges',
            error_codes='403',
            database_involved='users'
        )
        if exceptionIfNotSatisfied:
            raise Forbidden('Access forbidden: insufficient privileges')
        else:
            return False
    return True


def getRoles(module, permission):
    ROLES, ROLE_EXECUTE, ROLE_READ, ROLE_WRITE = load_roles_from_db(ignore_submodule=True)
    if module == '*':
        if permission == 'write':
            return ROLE_WRITE
        elif permission == 'read':
            return ROLE_READ
        elif permission == 'execute':
            return ROLE_EXECUTE
    else:
        return ROLES['module'][module][permission]


def load_roles_from_db(ignore_submodule=False):
    logger = get_logger(__name__)
    try:
        role_permission_list = [role_permission.to_dict() for role_permission in Role.query.all()]
        if ignore_submodule:
            # omit 'module' after '__' (which specifies submodule)
            for i in range(len(role_permission_list)):
                role_permission_list[i]["module"] = role_permission_list[i]["module"].split('__')[0]

    except Exception as e:
        # if db is not ready, take a default role_permission
        logger.exception(e)
        logger.debug("Roles table in database is not up")
        role_permission_list = [
            {"name": "User Access Rights", "module": "uam", "permission_type": "read"},
            {"name": "User Access Rights", "module": "uam", "permission_type": "write"},
            {"name": "User Access Rights", "module": "uam", "permission_type": "execute"},
            {"name": "User Access Rights", "module": "log", "permission_type": "read"},
            {"name": "User Access Rights", "module": "log", "permission_type": "write"},
            {"name": "User Access Rights", "module": "log", "permission_type": "execute"},
        ]

    roles = {}
    for role_permission in role_permission_list:
        role_name = role_permission["name"]
        module = role_permission["module"]
        permission = role_permission["permission_type"]
        if not role_name in roles.keys():
            roles[role_name] = {"read": [], "write": [], "execute": []}
        roles[role_name][permission].append(module)
    ROLES = {}
    ROLES["roles"] = roles
    roles_per_module = {}
    for role_permission in role_permission_list:
        role_name = role_permission["name"]
        module = role_permission["module"]
        permission = role_permission["permission_type"]
        if not module in roles_per_module.keys():
            roles_per_module[module] = {"read": [], "write": [], "execute": []}
        roles_per_module[module][permission].append(role_name)
    ROLES["module"] = roles_per_module
    ROLE_EXECUTE = list(set(
        (ROLES['module']['uam']['execute'] if ('uam' in ROLES['module'] and 'execute' in ROLES['module']['uam']) else []) +
        (ROLES['module']['cem']['execute'] if ('cem' in ROLES['module'] and 'execute' in ROLES['module']['cem']) else []) +
        (ROLES['module']['bottomup']['execute'] if ('bottomup' in ROLES['module'] and 'execute' in ROLES['module']['bottomup']) else []) +
        (ROLES['module']['physical']['execute'] if ('physical' in ROLES['module'] and 'execute' in ROLES['module']['physical']) else []) +
        (ROLES['module']['netzero']['execute'] if ('netzero' in ROLES['module'] and 'execute' in ROLES['module']['netzero']) else []) +
        (ROLES['module']['frtb']['execute'] if ('frtb' in ROLES['module'] and 'execute' in ROLES['module']['frtb']) else []) +
        (ROLES['module']['pcaf']['execute'] if ('pcaf' in ROLES['module'] and 'execute' in ROLES['module']['pcaf']) else [])
    ))
    ROLE_READ = list(set(
        (ROLES['module']['uam']['read'] if ('uam' in ROLES['module'] and 'read' in ROLES['module']['uam']) else []) +
        (ROLES['module']['cem']['read'] if ('cem' in ROLES['module'] and 'read' in ROLES['module']['cem']) else []) +
        (ROLES['module']['bottomup']['read'] if ('bottomup' in ROLES['module'] and 'read' in ROLES['module']['bottomup']) else []) +
        (ROLES['module']['physical']['read'] if ('physical' in ROLES['module'] and 'read' in ROLES['module']['physical']) else []) +
        (ROLES['module']['netzero']['read'] if ('netzero' in ROLES['module'] and 'read' in ROLES['module']['netzero']) else []) +
        (ROLES['module']['frtb']['read'] if ('frtb' in ROLES['module'] and 'read' in ROLES['module']['frtb']) else []) +
        (ROLES['module']['pcaf']['read'] if ('pcaf' in ROLES['module'] and 'read' in ROLES['module']['pcaf']) else [])
    ))
    ROLE_WRITE = list(set(
        (ROLES['module']['uam']['write'] if ('uam' in ROLES['module'] and 'write' in ROLES['module']['uam']) else []) +
        (ROLES['module']['cem']['write'] if ('cem' in ROLES['module'] and 'write' in ROLES['module']['cem']) else []) +
        (ROLES['module']['bottomup']['write'] if ('bottomup' in ROLES['module'] and 'write' in ROLES['module']['bottomup']) else []) +
        (ROLES['module']['physical']['write'] if ('physical' in ROLES['module'] and 'write' in ROLES['module']['physical']) else []) +
        (ROLES['module']['netzero']['write'] if ('netzero' in ROLES['module'] and 'write' in ROLES['module']['netzero']) else []) +
        (ROLES['module']['frtb']['write'] if ('frtb' in ROLES['module'] and 'write' in ROLES['module']['frtb']) else []) +
        (ROLES['module']['pcaf']['write'] if ('pcaf' in ROLES['module'] and 'write' in ROLES['module']['pcaf']) else [])
    ))
    return ROLES, ROLE_EXECUTE, ROLE_READ, ROLE_WRITE
