import pytest
from rest_framework.test import APIClient
from users.models import User
from projects.models import Project, Membership, Task


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email='meera@taskboard.dev', name='Meera Iyer', password='password123')


@pytest.fixture
def auth_client(client, user):
    response = client.post('/api/auth/login', {
        'email': 'meera@taskboard.dev',
        'password': 'password123',
    }, format='json')
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['token']}")
    return client


@pytest.mark.django_db
class TestProjects:
    def test_create_project(self, auth_client, user):
        response = auth_client.post('/api/projects', {'name': 'My Project'}, format='json')
        assert response.status_code == 201
        assert response.data['project']['name'] == 'My Project'

    def test_list_only_returns_member_projects(self, auth_client, user):
        p1 = Project.objects.create(name='Mine', owner=user)
        Membership.objects.create(user=user, project=p1, role='admin')
        other = User.objects.create_user(email='other@example.com', name='Other', password='password123')
        p2 = Project.objects.create(name='Not Mine', owner=other)
        Membership.objects.create(user=other, project=p2, role='admin')

        response = auth_client.get('/api/projects')
        assert response.status_code == 200
        names = [p['name'] for p in response.data['projects']]
        assert 'Mine' in names
        assert 'Not Mine' not in names

    def test_get_project_detail(self, auth_client, user):
        project = Project.objects.create(name='My Project', owner=user)
        Membership.objects.create(user=user, project=project, role='admin')

        response = auth_client.get(f'/api/projects/{project.id}')
        assert response.status_code == 200
        assert response.data['project']['name'] == 'My Project'

    def test_non_member_cannot_view_project(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='Private', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.get(f'/api/projects/{project.id}')
        assert response.status_code == 403


@pytest.mark.django_db
class TestTasks:
    def test_create_task(self, auth_client, user):
        project = Project.objects.create(name='P', owner=user)
        Membership.objects.create(user=user, project=project, role='admin')

        response = auth_client.post(f'/api/projects/{project.id}/tasks', {'title': 'Do a thing'}, format='json')
        assert response.status_code == 201
        assert response.data['task']['title'] == 'Do a thing'

    def test_viewers_cannot_create_tasks(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        Membership.objects.create(user=user, project=project, role='viewer')

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.post(f'/api/projects/{project.id}/tasks', {'title': 'A task'}, format='json')
        assert response.status_code == 403

    def test_delete_task_requires_membership(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        task = Task.objects.create(project=project, title='A task', created_by=owner)

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.delete(f'/api/tasks/{task.id}')
        assert response.status_code == 403


@pytest.mark.django_db
class TestTaskSearch:
    @pytest.fixture
    def project(self, user):
        project = Project.objects.create(name='P', owner=user)
        Membership.objects.create(user=user, project=project, role='admin')
        Task.objects.create(project=project, title='Record demo video', description='for launch', created_by=user, position=0)
        Task.objects.create(project=project, title='Draft press release', description='mention the VIDEO', created_by=user, position=1)
        Task.objects.create(project=project, title='Book venue', description=None, created_by=user, position=2)
        return project

    def _titles(self, response):
        return [t['title'] for t in response.data['tasks']]

    def test_search_matches_title_case_insensitive(self, auth_client, project):
        response = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': 'DEMO'})
        assert response.status_code == 200
        assert self._titles(response) == ['Record demo video']

    def test_search_matches_description(self, auth_client, project):
        response = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': 'video'})
        assert self._titles(response) == ['Record demo video', 'Draft press release']

    def test_search_no_match(self, auth_client, project):
        response = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': 'zzz'})
        assert response.data['tasks'] == []

    def test_search_scoped_to_project(self, auth_client, user, project):
        other = Project.objects.create(name='Other', owner=user)
        Membership.objects.create(user=user, project=other, role='admin')
        Task.objects.create(project=other, title='Other video', created_by=user)
        response = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': 'Other'})
        assert response.data['tasks'] == []

    @pytest.mark.parametrize('payload', [
        "x' OR 'x%'='x",
        "x%' OR (SELECT COUNT(*) FROM users)>'0' OR 'x%'='x",
        "'; DROP TABLE tasks; --",
    ])
    def test_search_sql_injection_returns_nothing(self, auth_client, project, payload):
        response = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': payload})
        assert response.status_code == 200
        assert response.data['tasks'] == []
        assert Task.objects.filter(project=project).count() == 3

    def test_search_uses_serializer_shape(self, auth_client, project):
        search = auth_client.get(f'/api/projects/{project.id}/tasks', {'q': 'venue'}).data['tasks'][0]
        listing = [t for t in auth_client.get(f'/api/projects/{project.id}/tasks').data['tasks'] if t['title'] == 'Book venue'][0]
        assert search == listing

    def test_search_requires_membership(self, client, project):
        User.objects.create_user(email='stranger@example.com', name='S', password='password123')
        resp = client.post('/api/auth/login', {'email': 'stranger@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
        assert client.get(f'/api/projects/{project.id}/tasks', {'q': 'video'}).status_code == 403


@pytest.mark.django_db
class TestComments:
    @pytest.fixture
    def setup(self, user):
        from projects.models import Comment
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        task = Task.objects.create(project=project, title='T', created_by=owner)
        return owner, project, task, Comment

    def _login(self, client, email):
        resp = client.post('/api/auth/login', {'email': email, 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

    @pytest.mark.parametrize('role', ['admin', 'member', 'viewer'])
    def test_any_member_reads_thread_with_author_and_time(self, client, user, setup, role):
        owner, project, task, Comment = setup
        Membership.objects.create(user=user, project=project, role=role)
        Comment.objects.create(task=task, author=owner, body='hello')
        self._login(client, 'meera@taskboard.dev')

        response = client.get(f'/api/tasks/{task.id}/comments')
        assert response.status_code == 200
        c = response.data['comments'][0]
        assert c['body'] == 'hello'
        assert c['author']['name'] == 'Owner'
        assert c['created_at']
        assert c['task_id'] == str(task.id)

    def test_oldest_first_with_stable_tiebreak(self, client, user, setup):
        from django.utils import timezone
        from datetime import timedelta
        owner, project, task, Comment = setup
        Membership.objects.create(user=user, project=project, role='viewer')
        now = timezone.now()
        late = Comment.objects.create(task=task, author=owner, body='late')
        first = Comment.objects.create(task=task, author=owner, body='first')
        tie_a = Comment.objects.create(task=task, author=owner, body='tie-a')
        tie_b = Comment.objects.create(task=task, author=owner, body='tie-b')
        Comment.objects.filter(id=late.id).update(created_at=now)
        Comment.objects.filter(id=first.id).update(created_at=now - timedelta(days=1))
        Comment.objects.filter(id__in=[tie_a.id, tie_b.id]).update(created_at=now - timedelta(hours=1))
        expected = ['first'] + [c.body for c in sorted([tie_a, tie_b], key=lambda c: c.id)] + ['late']
        self._login(client, 'meera@taskboard.dev')

        response = client.get(f'/api/tasks/{task.id}/comments')
        assert [c['body'] for c in response.data['comments']] == expected

    def test_non_member_gets_403_without_data(self, client, user, setup):
        owner, project, task, Comment = setup
        Comment.objects.create(task=task, author=owner, body='secret')
        self._login(client, 'meera@taskboard.dev')

        response = client.get(f'/api/tasks/{task.id}/comments')
        assert response.status_code == 403
        assert 'comments' not in response.data
        assert 'secret' not in str(response.data)

    def test_member_of_other_project_cannot_read(self, client, user, setup):
        owner, project, task, Comment = setup
        other = Project.objects.create(name='Other', owner=user)
        Membership.objects.create(user=user, project=other, role='admin')
        Comment.objects.create(task=task, author=owner, body='secret')
        self._login(client, 'meera@taskboard.dev')

        assert client.get(f'/api/tasks/{task.id}/comments').status_code == 403

    def test_unauthenticated_rejected(self, client, setup):
        owner, project, task, Comment = setup
        assert client.get(f'/api/tasks/{task.id}/comments').status_code in (401, 403)

    def test_unknown_task_404(self, auth_client):
        import uuid
        assert auth_client.get(f'/api/tasks/{uuid.uuid4()}/comments').status_code == 404

    def test_deleting_task_deletes_thread(self, setup):
        owner, project, task, Comment = setup
        Comment.objects.create(task=task, author=owner, body='x')
        task.delete()
        assert Comment.objects.count() == 0

    def test_deleting_author_keeps_comments(self, client, user, setup):
        owner, project, task, Comment = setup
        author = User.objects.create_user(email='gone@example.com', name='Gone', password='password123')
        Comment.objects.create(task=task, author=author, body='stays')
        Membership.objects.create(user=user, project=project, role='viewer')
        author.delete()
        self._login(client, 'meera@taskboard.dev')

        response = client.get(f'/api/tasks/{task.id}/comments')
        assert response.status_code == 200
        assert response.data['comments'][0]['body'] == 'stays'
        assert response.data['comments'][0]['author'] is None

    def test_authors_loaded_without_per_comment_queries(self, client, user, setup, django_assert_max_num_queries):
        owner, project, task, Comment = setup
        Membership.objects.create(user=user, project=project, role='viewer')
        for i in range(5):
            Comment.objects.create(task=task, author=owner, body=str(i))
        self._login(client, 'meera@taskboard.dev')
        with django_assert_max_num_queries(6):
            assert client.get(f'/api/tasks/{task.id}/comments').status_code == 200
