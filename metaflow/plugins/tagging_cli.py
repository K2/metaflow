import click
from metaflow import namespace
from metaflow.util import resolve_identity
from metaflow.exception import CommandException, MetaflowNotFound
from metaflow.exception import MetaflowNamespaceMismatch

# a rough emulation of itertools.zip_longest for our needs
# because it's not available in py2
def zip_longest(list1, list2):
    if (len(list1) < len(list2)):
        list1.extend([None] * (len(list2) - len(list1)))
    elif (len(list1) > len(list2)):
        list2.extend([None] * (len(list1) - len(list2)))
    return zip(list1, list2)

def format_tags(system_tags, customized_tags):
    import sys

    header = ("*system tags (immutable)*", "*customized tags*")
    stag_width = max([len(tag) for tag in list(system_tags) + [header[0]]])
    ctag_width = max([len(tag) for tag in list(customized_tags) + [header[1]]])

    # * * is hidden away by echo, hence the + 2
    header_formatter = "{0:%d}  {1}" % (stag_width + 2)
    lines = [header_formatter.format(*header)]

    formatter = "{0:%d}  {1}" % (stag_width)
    # seperator line under header
    lines.extend([formatter.format("-" * stag_width, "-" * ctag_width)])

    for stag, ctag in zip_longest(sorted(system_tags), sorted(customized_tags)):
        stag = stag if stag is not None else ""
        ctag = ctag if ctag is not None else ""
        if sys.version_info[0] < 3:
            ctag = ctag.encode('utf-8')
        lines.extend([formatter.format(stag, ctag)])

    return "\n".join(lines)


def print_tags(metaflow_run_client):
    system_tags = metaflow_run_client.system_tags
    customized_tags = metaflow_run_client.tags.difference(system_tags)
    return format_tags(system_tags, customized_tags)


def check_run_id(user_namespace, flow_name, run_id):
    from metaflow.client import Flow

    if run_id is None:
        latest_run_id = Flow(pathspec=flow_name).latest_run.id
        msg = "Please run with --run-id: tag add --run-id TEXT YOUR-TAGS\n" + \
              "Flow %s's latest run has run-id *%s* under namespace %s" \
            % (flow_name, latest_run_id, user_namespace)
        raise CommandException(msg)


def is_prod_token(token):
    return token is not None and token.startswith("production:")

def obtain_metaflow_run_client(obj, run_id, user_namespace):
    from metaflow.client import Run, Flow

    if is_prod_token(user_namespace):
        raise CommandException(
            "Modifying a scheduled run's tags is currently not allowed.")

    flow_name = obj.flow.name

    # handle error messaging for two cases
    # 1. our user tries to tagging a new flow before it is run
    # 2. our user makes a typo in --namespace
    try:
        namespace(user_namespace)
        Flow(pathspec=flow_name)
    except MetaflowNotFound:
        raise CommandException("Flow *%s* does not exist " % flow_name +
                               "in any namespace.\n" +
                               "Please run the flow before tagging.")
    except MetaflowNamespaceMismatch:
        raise CommandException("Flow *%s* does not belong to " % flow_name +
                               "namespace *%s*.\n" % user_namespace +
                               "Check typos if you used option --namespace.")

    # throw an error with message to include latest run-id when run_id is None
    check_run_id(user_namespace, flow_name, run_id)

    run_name = "%s/%s" % (flow_name, run_id)

    # handle error messaging for three cases
    # 1. our user makes a typo in --run-id
    # 2. our user tries to mutate tags on a meson/production run
    # 3. our user's --run-id does not exist in the default/specified namespace
    try:
        namespace(user_namespace)
        metaflow_client = Run(pathspec=run_name)
    except MetaflowNotFound:
        raise CommandException("Run *%s* does not exist " % run_name +
                               "in any namespace.\nPlease check your --run-id.")
    except MetaflowNamespaceMismatch as e:
        namespace(None)
        metaflow_client = Run(pathspec=run_name)

        run_tags = metaflow_client.tags

        if any([is_prod_token(tag) for tag in run_tags]):
            raise CommandException(
                "Modifying a scheduled run's tags is currently not allowed.")

        msg = "Run *%s* does not belong to " % run_name + \
            "namespace *%s*.\n" % user_namespace

        user_tags = [tag for tag in run_tags if tag.startswith("user:")]
        if user_tags:
            msg += "You can choose any of the following tags associated with *%s* " % run_name + \
                   "to use with option *--namespace*\n"
            msg += "\n".join(["\t*%s*" % tag for tag in user_tags])

        raise CommandException(msg)

    return metaflow_client


def list_runs(obj, user_namespace):
    from metaflow.client import Flow

    namespace(user_namespace)
    metaflow_client = Flow(pathspec=obj.flow.name)
    return metaflow_client.runs()


@click.group()
def cli():
    pass


@cli.group(help='Commands related to Metaflow tagging.')
def tag():
    pass

@tag.command('add',
             help='Add tags to a run.')
@click.option('--run-id',
              required=False,  # set False here so we can throw a better error message
              default=None,
              type=str,
              help="Run ID of the specific run to tag.  [required]")
@click.option('--namespace',
              'user_namespace',
              required=False,
              default=None,
              type=str,
              help="Change namespace from the default (your username) to "
                   "the specified tag.")
@click.argument('tags',
                required=True,
                type=str,
                nargs=-1)
@click.pass_obj
def add(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    metaflow_run_client = obtain_metaflow_run_client(obj,
                                                     run_id, user_namespace)

    metaflow_run_client.add_tag(list(tags))

    obj.echo("Operation successful. New tags:", err=False)
    obj.echo(print_tags(metaflow_run_client), err=False)


@tag.command('remove',
             help='Remove tags from a run.')
@click.option('--run-id',
              required=False,  # set False here so we can throw a better error message
              default=None,
              type=str,
              help="Run ID of the specific run to tag.  [required]")
@click.option('--namespace',
              'user_namespace',
              required=False,
              default=None,
              type=str,
              help="Change namespace from the default (your username) to "
                   "the specified tag.")
@click.argument('tags',
                required=True,
                type=str,
                nargs=-1)
@click.pass_obj
def remove(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    metaflow_run_client = obtain_metaflow_run_client(obj,
                                                     run_id, user_namespace)

    metaflow_run_client.remove_tag(list(tags))

    obj.echo("Operation successful. New tags:")
    obj.echo(print_tags(metaflow_run_client))

@tag.command('replace',
             help='Replace tags of a run.')
@click.option('--run-id',
              required=False,  # set False here so we can throw a better error message
              default=None,
              type=str,
              help="Run ID of the specific run to tag.  [required]")
@click.option('--namespace',
              'user_namespace',
              required=False,
              default=None,
              type=str,
              help="Change namespace from the default (your username) to "
                   "the specified tag.")
@click.argument('tags',
                required=True,
                type=str,
                nargs=2)
@click.pass_obj
def replace(obj, run_id, user_namespace, tags):
    user_namespace = resolve_identity() if user_namespace is None else user_namespace
    metaflow_run_client = obtain_metaflow_run_client(obj,
                                                     run_id, user_namespace)

    metaflow_run_client.replace_tag([tags[0]], [tags[1]])

    obj.echo("Operation successful. New tags:")
    obj.echo(print_tags(metaflow_run_client))

@tag.command('list',
             help='List tags of a run.')
@click.option('--run-id',
              required=False,
              default=None,
              type=str,
              help="Run ID of the specific run to list.")
@click.option('--all',
              'list_all',
              required=False,
              is_flag=True,
              default=False,
              help="List tags across all runs of this flow.")
@click.option('--my-runs',
              'my_runs',
              required=False,
              is_flag=True,
              default=False,
              help="List tags across all runs of the flow under the default namespaces.")
@click.option('--hide-system-tags',
              required=False,
              is_flag=True,
              default=False,
              help="Hide system tags.")
@click.pass_obj
def tag_list(obj, run_id, hide_system_tags, list_all, my_runs):
    if (run_id is None and not list_all and not my_runs):
        raise CommandException(
            "Please use one of the options --run-id / --all / --my-runs.\n" +
            "You can run the flow with commands 'tag list --help' " +
            "to check the meaning of the three options."
        )

    if (list_all and my_runs):
        raise CommandException("Option --all cannot be used together with --my-runs.\n" +
                               "You can run the flow with commands 'tag list --help' " +
                               "to check the meaning of the two options.")

    system_tags = set()
    customized_tags = set()

    if list_all or my_runs:
        user_namespace = resolve_identity() if my_runs else None
        runs = list_runs(obj, user_namespace)
        for run in runs:
            system_tags = system_tags.union(run.system_tags)
            customized_tags = customized_tags.union(
                run.tags.difference(run.system_tags))
    else:
        metaflow_run_client = obtain_metaflow_run_client(obj,
                                                         run_id, None)
        system_tags = metaflow_run_client.system_tags
        customized_tags = metaflow_run_client.tags.difference(system_tags)

    if hide_system_tags:
        obj.echo(format_tags([], customized_tags), err=False)
    else:
        obj.echo(format_tags(system_tags, customized_tags), err=False)